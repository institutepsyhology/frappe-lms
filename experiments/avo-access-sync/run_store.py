"""One bounded-memory MVC bench worker for a verified private gzip payload.

The immutable Frappe ledger is the resume checkpoint: replaying a payload checks
existing rows rather than trusting a cursor after a lost commit acknowledgement.
The worker never enrolls students or changes course publication.
"""
import argparse
import gzip
import hashlib
import json
import os
import re
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import target_sync as target


def digest_file(path):
    result = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            result.update(block)
    return result.hexdigest()


def save_state(path, state):
    path = Path(path)
    temporary = path.with_name(path.name + '.new')
    with temporary.open('w', encoding='utf-8') as stream:
        json.dump(state, stream, ensure_ascii=True, sort_keys=True)
        stream.write('\n')
        stream.flush()
        os.fsync(stream.fileno())
    os.chmod(temporary, 0o600)
    temporary.replace(path)


def event(path, **value):
    value['at'] = datetime.now(timezone.utc).isoformat()
    with Path(path).open('a', encoding='utf-8') as stream:
        stream.write(json.dumps(value, ensure_ascii=True, sort_keys=True) + '\n')
        stream.flush()


def verify_payload(payload, manifest):
    """Validate the whole bounded stream before any schema or record write."""
    if type(manifest) is not dict:
        raise target.Rejected('payload_manifest_mismatch')
    expected = manifest.get('payload', {})
    if (manifest.get('account') != target.ACCOUNT or manifest.get('origin') != target.ORIGIN
            or type(manifest.get('record_count')) is not int or manifest['record_count'] < 1
            or type(manifest.get('lesson_count')) is not int or manifest['lesson_count'] < 0
            or type(expected) is not dict
            or any(type(expected.get(key)) is not str or not re.fullmatch(r'[0-9a-f]{64}', expected[key])
                   for key in ('compressed_sha256', 'aggregate_payload_hash'))
            or digest_file(payload) != expected['compressed_sha256']):
        raise target.Rejected('payload_manifest_mismatch')
    aggregate = hashlib.sha256()
    count = lessons = 0
    previous = None
    batch = []
    try:
        with gzip.open(payload, 'rt', encoding='utf-8') as source:
            for line in source:
                if len(line) > 2_000_000:
                    raise target.Rejected('source_line_too_large')
                record = json.loads(line)
                ident = record.get('source_access_id') if type(record) is dict else None
                if not target._id(ident) or (previous is not None and ident <= previous):
                    raise target.Rejected('payload_order_or_duplicate')
                previous = ident
                value = hashlib.sha256(target._canonical(record).encode('utf-8')).hexdigest()
                aggregate.update((ident + ':' + value + '\n').encode('ascii'))
                lessons += len(record.get('lessons', []))
                count += 1
                batch.append(record)
                if len(batch) >= target.MAX_BATCH:
                    target._validate_records(batch)
                    batch.clear()
        if batch:
            target._validate_records(batch)
    except target.Rejected:
        raise
    except Exception:
        raise target.Rejected('invalid_payload_stream') from None
    if (count != manifest['record_count'] or lessons != manifest['lesson_count']
            or aggregate.hexdigest() != expected['aggregate_payload_hash']):
        raise target.Rejected('payload_manifest_mismatch')


def run(fr, payload, manifest, state_path, events_path, limit=None):
    target._require(fr)
    if type(manifest) is not dict:
        state = {'status': 'stopped', 'pid': os.getpid(), 'processed': 0,
                 'error': 'payload_manifest_mismatch'}
        save_state(state_path, state)
        event(events_path, status='stopped', code='payload_manifest_mismatch', processed=0)
        raise target.Rejected('payload_manifest_mismatch')
    expected = manifest.get('payload', {})
    state = {'status': 'validating', 'pid': os.getpid(), 'processed': 0, 'stored': 0,
             'already_stored': 0, 'expected': manifest.get('record_count'), 'statuses': {},
             'compressed_sha256': expected.get('compressed_sha256') if type(expected) is dict else None}
    save_state(state_path, state)

    def stop(exc):
        code = str(exc) if isinstance(exc, target.Rejected) else 'unexpected_worker_failure'
        if not re.fullmatch(r'[a-z_]{1,80}', code):
            code = 'unexpected_worker_failure'
        state.update(status='stopped', error=code)
        event(events_path, status='stopped', code=code, processed=state['processed'])
        save_state(state_path, state)
        raise target.Rejected(code) from None

    try:
        if limit is not None and (type(limit) is not int or limit < 1):
            raise target.Rejected('invalid_limit')
        verify_payload(payload, manifest)
        target.ensure_schema(fr)
    except Exception as exc:
        stop(exc)
    state['status'] = 'running'
    save_state(state_path, state)
    rolling = hashlib.sha256()
    statuses = Counter()
    lessons = 0
    previous_id = None
    batch = []

    def flush():
        if not batch:
            return
        result = target.store_batch(fr, batch)
        state['processed'] += len(batch)
        state['stored'] += result['stored']
        state['already_stored'] += result['already_stored']
        statuses.update(result['statuses'])
        state['statuses'] = dict(statuses)
        event(events_path, status='batch_verified', first_id=batch[0]['source_access_id'],
              last_id=batch[-1]['source_access_id'], count=len(batch), **result)
        save_state(state_path, state)
        batch.clear()

    try:
        with gzip.open(payload, 'rt', encoding='utf-8') as source:
            for line in source:
                if len(line) > 2_000_000:
                    raise target.Rejected('source_line_too_large')
                record = json.loads(line)
                ident = record.get('source_access_id') if type(record) is dict else None
                if not target._id(ident) or (previous_id is not None and ident <= previous_id):
                    raise target.Rejected('payload_order_or_duplicate')
                previous_id = ident
                canonical = target._canonical(record)
                value = hashlib.sha256(canonical.encode('utf-8')).hexdigest()
                rolling.update((ident + ':' + value + '\n').encode('ascii'))
                lessons += len(record.get('lessons', []))
                batch.append(record)
                if len(batch) >= target.MAX_BATCH or (limit and state['processed'] + len(batch) >= limit):
                    flush()
                if limit and state['processed'] >= limit:
                    state['status'] = 'pilot_complete'
                    save_state(state_path, state)
                    return state
        flush()
        if (state['processed'] != manifest['record_count'] or lessons != manifest.get('lesson_count')
                or rolling.hexdigest() != expected.get('aggregate_payload_hash')):
            raise target.Rejected('final_source_fingerprint_mismatch')
        rows = fr.get_all(target.DOCTYPE, filters={'account': target.ACCOUNT},
                          fields=['source_access_id', 'payload_hash'], order_by='source_access_id asc',
                          limit_page_length=0)
        persisted = hashlib.sha256()
        for row in rows:
            persisted.update((row['source_access_id'] + ':' + row['payload_hash'] + '\n').encode('ascii'))
        if len(rows) != state['processed'] or persisted.hexdigest() != rolling.hexdigest():
            raise target.Rejected('final_target_fingerprint_mismatch')
        state.update(status='completed', aggregate_payload_hash=rolling.hexdigest(),
                     lesson_count=lessons, target_verified=True)
        event(events_path, status='completed', count=state['processed'],
              aggregate_payload_hash=rolling.hexdigest())
        save_state(state_path, state)
        return state
    except Exception as exc:
        stop(exc)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--payload', type=Path, required=True)
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--state', type=Path, required=True)
    parser.add_argument('--events', type=Path, required=True)
    parser.add_argument('--limit', type=int)
    args = parser.parse_args()
    import fcntl
    import frappe
    with args.state.with_suffix('.lock').open('a') as lock:
        try:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print(json.dumps({'ok': False, 'error': 'worker_already_running'}))
            return 1
        frappe.init(site=target.SITE)
        frappe.connect()
        frappe.set_user('Administrator')
        try:
            manifest = json.loads(args.manifest.read_text(encoding='utf-8'))
            result = run(frappe, args.payload, manifest, args.state, args.events, args.limit)
            print(json.dumps({'ok': True, 'result': result}, ensure_ascii=True))
            return 0
        except Exception:
            print(json.dumps({'ok': False, 'error': 'access_worker_stopped'}))
            return 1
        finally:
            frappe.destroy()


if __name__ == '__main__':
    raise SystemExit(main())

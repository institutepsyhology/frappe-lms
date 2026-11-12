"""Isolated, resumable Master Vision collection and draft-only MCP migration."""
import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import threading
from urllib.parse import urljoin

import source
from storage import Store, StorageError, ACCOUNT, ORIGIN, SITE

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
DATA = ROOT / 'exports/lesson-content/mastervision-migration'
MAX_ERRORS = 10
IDENTITY_ERRORS = {'wrong_account_origin', 'source_identity_mismatch', 'course_identity_unconfirmed',
                   'lesson_identity_unconfirmed', 'invalid_id', 'source_auth_error'}


class Stop(RuntimeError):
    pass


class Transport:
    def __init__(self):
        self.process = subprocess.Popen(['node', str(HERE / 'transport.cjs')], stdin=subprocess.PIPE,
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))

    def get(self, url):
        if not isinstance(url, str) or not url.startswith(ORIGIN + '/'):
            raise Stop('wrong_source_origin')
        result = []
        def read():
            try:
                result.append(self.process.stdout.readline(70 * 1024 * 1024))
            except Exception:
                result.append(b'')
        try:
            self.process.stdin.write((json.dumps({'url': url}) + '\n').encode())
            self.process.stdin.flush()
            thread = threading.Thread(target=read, daemon=True)
            thread.start(); thread.join(timeout=65)
            if thread.is_alive():
                raise Stop('source_timeout')
            if not result or not result[0].endswith(b'\n'):
                raise Stop('source_transport_failed')
            reply = json.loads(result[0])
            if reply.get('ok') is not True:
                code = reply.get('error', '')
                raise Stop(code if isinstance(code, str) and re.fullmatch('[a-z_]{1,80}', code) else 'source_transport_failed')
            if not isinstance(reply.get('html'), str):
                raise Stop('source_response_invalid')
            return reply['html']
        except (BrokenPipeError, OSError, ValueError):
            raise Stop('source_transport_failed') from None

    def close(self):
        try:
            self.process.stdin.close()
            self.process.wait(timeout=5)
        except Exception:
            self.process.kill(); self.process.wait(timeout=5)

    def __enter__(self): return self
    def __exit__(self, *_): self.close()


def archive(store, kind, cid, lid, html, parsed=None, error=None):
    return store.capture(kind, cid, lid, {'account': ACCOUNT, 'origin': ORIGIN, 'html': html,
        'parsed': parsed, 'verified': parsed is not None, 'error': error})


def catalog(store, transport):
    rows, total, expected, page = [], None, 1, 1
    url = ORIGIN + source.CATALOG + '?lg=ru'
    seen_urls = set()
    while url:
        if url in seen_urls or page > 10000:
            raise Stop('catalog_pagination_loop')
        seen_urls.add(url)
        html = transport.get(url)
        try:
            parsed = source.parse_catalog(html, page=page)
        except source.Review as exc:
            archive(store, 'catalog', 0, page, html, error=str(exc))
            raise
        archive(store, 'catalog', 0, page, html, parsed=parsed)
        if parsed['start'] != expected or (total is not None and parsed['total'] != total):
            raise Stop('catalog_changed_during_collection')
        total, expected = parsed['total'], parsed['end'] + 1
        rows.extend(parsed['courses'])
        emit({'stage': 'catalog', 'page': page, 'observed': len(rows), 'total': total})
        url = parsed['next_url']
        page += 1
    if not total or len(rows) != total or len({row['id'] for row in rows}) != total:
        raise Stop('catalog_incomplete')
    store.catalog(rows)
    store.event('catalog', None, None, 'complete')
    return sorted(rows, key=lambda row: row['id'])


def course(store, transport, cid):
    html = transport.get(ORIGIN + source.COURSE + '?id=' + str(cid) + '&lg=ru')
    try:
        parsed = source.parse_course(html, cid)
    except source.Review as exc:
        archive(store, 'course', cid, 0, html, error=str(exc)); raise
    digest = archive(store, 'course', cid, 0, html, parsed=parsed)
    payloads, lesson_digests = [], []
    for row in parsed['lessons']:
        lid = row['id']
        html = transport.get(ORIGIN + source.LESSON + '?id=' + str(lid) + '&lg=ru')
        try:
            item = source.parse_lesson(html, cid, lid, parsed['title'], row['title'])
        except source.Review as exc:
            archive(store, 'lesson', cid, lid, html, error=str(exc))
            store.event('collect', cid, lid, 'review', [str(exc)]); raise
        lesson_digests.append((lid, archive(store, 'lesson', cid, lid, html, parsed=item)))
        payloads.append(item['payload'])
        store.event('collect', cid, lid, 'captured')
    html = transport.get(ORIGIN + source.COURSE + '?id=' + str(cid) + '&lg=ru')
    try:
        after = source.parse_course(html, cid)
    except source.Review as exc:
        archive(store, 'course', cid, 0, html, error=str(exc)); raise
    if (after['lesson_ids'] != parsed['lesson_ids'] or after['title'] != parsed['title'] or
            [(x['id'], x['title']) for x in after['lessons']] != [(x['id'], x['title']) for x in parsed['lessons']] or
            after['tree'] != parsed['tree'] or after['settings'] != parsed['settings'] or
            after['cover_url'] != parsed['cover_url']):
        archive(store, 'course', cid, 0, html, parsed=after)
        raise source.Review('course_changed_during_collection')
    store.bind_course(cid, digest, lesson_digests)
    store.event('collect', cid, None, 'complete')
    return payloads


def stored_course(store, cid):
    try:
        return store.completed_course(cid)
    except StorageError as exc:
        if str(exc) == 'completed_course_checkpoint_missing':
            raise source.Review(str(exc)) from None
        raise Stop(str(exc)) from None


def prepare_payloads(payloads):
    from importer import Review as ImportReview
    from normalize_source import normalize_payload
    prepared, warnings = [], []
    for payload in payloads:
        try:
            normalized, codes = normalize_payload(payload)
        except ImportReview as exc:
            if str(exc) in ('normalization_account_mismatch', 'normalization_metadata_conflict', 'normalization_source_invalid'):
                raise Stop(str(exc)) from None
            # The unchanged source still goes through the stricter server parser.
            # Unknown embeds are never silently dropped or locally authorized.
            normalized, codes = payload, ['embedded_iframe_requires_review']
        prepared.append(normalized)
        if codes:
            warnings.append({'lesson_id': str(payload['lesson_id']), 'codes': codes})
    return prepared, warnings


def emit(value):
    print(json.dumps(value, ensure_ascii=False), flush=True)


def main():
    args = argparse.ArgumentParser(description=__doc__)
    args.add_argument('--catalog-only', action='store_true')
    args.add_argument('--collect-only', action='store_true')
    args.add_argument('--apply', action='store_true')
    args.add_argument('--limit', type=int)
    args.add_argument('--course', type=int)
    args.add_argument('--resume', action='store_true')
    args.add_argument('--stored', action='store_true', help='Use verified private snapshots without refreshing AVO')
    args.add_argument('--from-course', type=int, default=1)
    selected = args.parse_args()
    if selected.limit is not None and selected.limit < 1 or selected.course is not None and selected.course < 1:
        raise Stop('invalid_selection')
    if selected.apply and (selected.collect_only or selected.catalog_only):
        raise Stop('conflicting_mode')
    with Store(DATA) as store:
        client = None
        try:
            if selected.resume:
                for stage in ('collect', 'import'): store.error(stage, False)
            paused = store.db.execute('SELECT stage FROM errors WHERE consecutive>=?', (MAX_ERRORS,)).fetchall()
            if paused: raise Stop('paused_after_ten_problems')
            from contextlib import nullcontext
            with (nullcontext(None) if selected.stored else Transport()) as transport:
                rows = ([dict(row) for row in store.db.execute('SELECT id,title FROM courses ORDER BY id')]
                        if selected.stored else catalog(store, transport))
                if not rows: raise Stop('catalog_missing')
                if selected.catalog_only:
                    emit({'status': 'catalog_complete', 'courses': len(rows)}); return 0
                if selected.course:
                    rows = [row for row in rows if row['id'] == selected.course]
                    if not rows: raise Stop('selected_course_not_in_catalog')
                rows = [row for row in rows if row['id'] >= selected.from_course]
                if selected.limit: rows = rows[:selected.limit]
                if not selected.collect_only:
                    import importer
                    client = importer.MCPClient(workspace=ROOT)
                    target = importer.Importer(client)
                for row in rows:
                    cid = row['id']
                    try:
                        payloads = stored_course(store, cid) if selected.stored else course(store, transport, cid)
                        store.error('collect', False)
                    except source.Review as exc:
                        store.mark(cid, 'review'); store.event('collect', cid, None, 'review', [str(exc)])
                        if str(exc) in IDENTITY_ERRORS: raise Stop(str(exc)) from None
                        emit({'course': cid, 'status': 'review', 'stage': 'collect', 'code': str(exc)})
                        if store.error('collect', True) >= MAX_ERRORS: raise Stop('paused_after_ten_collection_problems')
                        store.report(); continue
                    if not payloads:
                        store.mark(cid, 'empty'); emit({'course': cid, 'status': 'empty'}); continue
                    if selected.collect_only:
                        emit({'course': cid, 'status': 'collected', 'lessons': len(payloads)}); continue
                    try:
                        payloads, normalization_warnings = prepare_payloads(payloads)
                        result = target.import_course(payloads, apply=selected.apply)
                        store.error('import', False)
                        if selected.apply: store.mark(cid, 'imported')
                        store.event('import', cid, None, result['status'])
                        for warning in result['warnings'] + normalization_warnings:
                            store.event('import', cid, int(warning['lesson_id']), 'warning', warning['codes'])
                        emit({'course': cid, 'status': result['status'], 'lessons': len(payloads),
                              'created': len(result['created_lesson_ids'])})
                    except importer.Review as exc:
                        store.mark(cid, 'review')
                        for problem in exc.problems or [{'lesson_id': None, 'codes': [str(exc)]}]:
                            lid = problem['lesson_id']
                            store.event('import', cid, int(lid) if lid else None, 'review', problem['codes'])
                        emit({'course': cid, 'status': 'review', 'stage': 'import'})
                        if store.error('import', True) >= MAX_ERRORS: raise Stop('paused_after_ten_import_problems')
                    store.report()
            emit({'status': 'finished', 'courses': store.summary()})
            return 0
        except (source.Review, Stop, StorageError) as exc:
            code = str(exc)
            if not re.fullmatch('[a-z0-9_]{1,100}', code): code = 'migration_stopped'
            store.event('catalog' if selected.catalog_only else 'collect', None, None, 'stopped', [code])
            emit({'status': 'stopped', 'code': code}); return 1
        except Exception as exc:
            import importer
            code = str(exc) if isinstance(exc, importer.Stop) and re.fullmatch('[a-z0-9_]{1,100}', str(exc)) else 'unexpected_failure'
            store.event('import', None, None, 'stopped', [code]); emit({'status': 'stopped', 'code': code}); return 1
        finally:
            store.report()
            if client: client.close()


if __name__ == '__main__':
    raise SystemExit(main())

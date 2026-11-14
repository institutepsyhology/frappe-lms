"""Finish the five owner-reviewed lessons using the installed MCP methods.

The intermediate appended lesson is a draft. Stop on any uncertain operation;
the journal lets an operator inspect a partially completed run before resuming.
"""
import argparse
import hashlib
import json
from pathlib import Path
import sys
from datetime import datetime, timezone

from importer import ACCOUNT, METHOD, MCPClient, Importer, Stop
from normalize_source import normalize_payload
from storage import Store, canonical

ROOT = Path(r'C:\codex\АВО-АВО')
ARCHIVE = ROOT / 'exports/lesson-content/mastervision-migration'
MANIFEST = ARCHIVE / 'ordered-insert-preflight-20261114.json'
MANIFEST_SHA = '0a14af938fa3bbf34e1f8e0793beead7265729c7b4cf6c3216c416707efb4209'
LOG = ARCHIVE / 'finish-five-background.jsonl'
EXPECTED = {(317, 2314), (624, 7050), (627, 7198), (630, 7295), (746, 8845)}

def log(status, **data):
    with LOG.open('a', encoding='utf8') as f:
        f.write(json.dumps({'at': datetime.now(timezone.utc).isoformat(), 'status': status, **data}, ensure_ascii=False) + '\n')
        f.flush()

def move(client, lesson, chapter, position):
    result = client.rpc('tools/call', {'name': 'call_method', 'arguments': {
        'method': 'lms.lms.api.update_lesson_index', 'args': {
            'lesson': lesson, 'sourceChapter': chapter, 'targetChapter': chapter, 'idx': position}}})
    if result.get('isError') or not isinstance(result.get('structuredContent'), dict):
        raise Stop('move_result_uncertain')

def run(apply):
    raw = MANIFEST.read_bytes()
    if hashlib.sha256(raw).hexdigest() != MANIFEST_SHA: raise Stop('manifest_changed')
    manifest = json.loads(raw)
    rows = manifest['courses']
    if manifest['account'] != ACCOUNT or {(x['course'], x['lesson']) for x in rows} != EXPECTED or len(rows) != 5:
        raise Stop('manifest_identity_invalid')
    client = MCPClient(ROOT)
    try:
        target = Importer(client)
        with Store(ARCHIVE) as store:
            for row in rows:
                cid, lid, before, pos = row['course'], row['lesson'], row['before'], row['position']
                ident = str(lid)
                payloads = store.completed_course(cid)
                matches = [p for p in payloads if p['lesson_id'] == lid]
                if len(matches) != 1 or row['image_sha256'] != {}: raise Stop('source_identity_invalid')
                payload, _ = normalize_payload(matches[0])
                if hashlib.sha256(canonical(payload)).hexdigest() != row['payload_sha256']:
                    raise Stop('source_payload_changed')
                outline = target.outline(str(cid))
                if outline['ids'] != before: raise Stop('course_order_changed')
                preview, _ = target.preview(payload, {})
                if preview['action'] != 'create_lesson': raise Stop('unexpected_preview')
                log('ready', course=cid, lesson=lid)
                if not apply: continue
                log('create_started', course=cid, lesson=lid)
                store.event('import', cid, lid, 'lesson_write_started')
                result = client.call('call_method', {'method': METHOD, 'args': {'payload': payload, 'images': {}, 'dry_run': False}}).get('result')
                if not isinstance(result, dict) or result.get('action') != 'created' or result.get('account') != ACCOUNT or result.get('course_id') != str(cid) or result.get('lesson_id') != ident or result.get('dry_run') is not False:
                    raise Stop('create_result_uncertain')
                appended = target.outline(str(cid))
                if appended['ids'] != before + [ident]: raise Stop('appended_order_uncertain')
                check, _ = target.preview(payload, {})
                if check['action'] != 'already_imported': raise Stop('created_content_uncertain')
                entry = appended['by_id'][ident]
                log('move_started', course=cid, lesson=lid)
                move(client, entry['name'], entry['chapter'], pos)
                desired = before[:pos] + [ident] + before[pos:]
                if target.outline(str(cid))['ids'] != desired: raise Stop('final_order_uncertain')
                check, _ = target.preview(payload, {})
                if check['action'] != 'already_imported': raise Stop('final_content_uncertain')
                store.event('import', cid, lid, 'lesson_created')
                log('complete', course=cid, lesson=lid)
        log('all_complete' if apply else 'preflight_complete')
    finally:
        client.close()

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    try:
        run(args.apply)
    except BaseException as exc:
        code = str(exc) if isinstance(exc, Stop) and len(str(exc)) < 100 else type(exc).__name__
        log('stopped', code=code)
        sys.exit(1)

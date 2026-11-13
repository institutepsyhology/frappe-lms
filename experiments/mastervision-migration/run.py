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
from storage import Store, StorageError, ACCOUNT, ORIGIN, SITE, STAGES

HERE = Path(__file__).resolve().parent
ROOT = Path(os.environ.get('MASTER_VISION_WORKSPACE', str(HERE.parents[2]))).resolve()
if not (ROOT / 'frappe-mcp/headers.py').is_file():
    raise RuntimeError('migration_workspace_unavailable')
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
        item = store.stable_lesson(cid, lid, item)
        lesson_digests.append((lid, archive(store, 'lesson', cid, lid, html, parsed=item)))
        payloads.append(item['payload'])
        store.event('collect', cid, lid, 'captured')
        if item.get('canonicalization'):
            store.event('collect', cid, lid, 'equivalent_source_reused', item['canonicalization'])
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


def target_course_ids(client):
    from importer import source_id
    targets = client.call('list_documents', {'doctype': 'LMS Course',
        'fields': ['name', 'custom_avo_account', 'custom_avo_id', 'custom_lms_id', 'published'],
        'filters': [['custom_avo_account', '=', ACCOUNT]], 'limit': 1000})
    documents = targets.get('documents')
    if not isinstance(documents, list) or targets.get('has_next_page') is not False:
        raise Stop('cover_target_catalog_invalid')
    target_ids = set()
    for row in documents:
        cid = source_id(row.get('custom_avo_id'))
        if (row.get('custom_avo_account') != ACCOUNT or row.get('custom_lms_id') != cid or cid in target_ids
                or not isinstance(row.get('name'), str) or not row['name']
                or type(row.get('published')) is not int or row['published'] != 0):
            raise Stop('cover_target_identity_invalid')
        target_ids.add(cid)
    return target_ids


def transfer_covers(store, rows, client, assets, apply):
    from covers import sync_cover
    from importer import Review as ImportReview
    target_ids = target_course_ids(client)
    for row in rows:
        cid = row['id']
        if str(cid) not in target_ids:
            continue
        metadata = store.completed_metadata(cid)
        if not metadata.get('cover_url'):
            emit({'course': cid, 'status': 'no_source_cover'}); continue
        try:
            raw, extension = assets.fetch(metadata['cover_url'])
            result = sync_cover(client, cid, raw, extension, apply=apply)
            store.error('cover', False)
            store.event('cover', cid, None, 'cover_' + result['status'])
            emit({'course': cid, 'status': 'cover_' + result['status']})
        except ImportReview as exc:
            store.event('cover', cid, None, 'review', [str(exc)])
            emit({'course': cid, 'status': 'cover_review', 'code': str(exc)})
            if store.error('cover', True) >= MAX_ERRORS:
                raise Stop('paused_after_ten_cover_problems')


def transfer_settings(store, rows, client, apply):
    from settings import ensure_private_course
    target_ids = target_course_ids(client)
    for row in rows:
        cid = row['id']
        if str(cid) not in target_ids:
            continue
        result = ensure_private_course(client, cid, apply=apply)
        store.event('settings', cid, None, 'private_' + result['status'])
        emit({'course': cid, 'status': 'private_' + result['status']})


def main():
    args = argparse.ArgumentParser(description=__doc__)
    args.add_argument('--catalog-only', action='store_true')
    args.add_argument('--collect-only', action='store_true')
    args.add_argument('--apply', action='store_true')
    args.add_argument('--limit', type=int)
    args.add_argument('--course', type=int, action='append', help='Select source course ID; repeat to select several')
    args.add_argument('--resume', action='store_true')
    args.add_argument('--stored', action='store_true', help='Use verified private snapshots without refreshing AVO')
    args.add_argument('--from-course', type=int, default=1)
    args.add_argument('--covers-only', action='store_true')
    args.add_argument('--settings-only', action='store_true')
    args.add_argument('--review-only', action='store_true', help='Process only courses currently awaiting review')
    args.add_argument('--audio-stage-only', action='store_true', help='Stage verified MP3 files directly on the MV server')
    selected = args.parse_args()
    if (selected.limit is not None and selected.limit < 1 or
            selected.course is not None and any(cid < 1 for cid in selected.course) or selected.from_course < 1):
        raise Stop('invalid_selection')
    if (selected.apply and (selected.collect_only or selected.catalog_only) or
            (selected.covers_only or selected.settings_only) and
            (not selected.stored or selected.collect_only or selected.catalog_only) or
            selected.covers_only and selected.settings_only or
            selected.review_only and (selected.covers_only or selected.settings_only or selected.catalog_only)):
        raise Stop('conflicting_mode')
    if selected.audio_stage_only and (not selected.stored or not selected.apply or selected.collect_only
            or selected.catalog_only or selected.covers_only or selected.settings_only or selected.review_only
            or selected.course or selected.limit or selected.from_course != 1):
        raise Stop('conflicting_mode')
    with Store(DATA) as store:
        client, assets = None, None
        try:
            if selected.resume:
                for stage in sorted(STAGES): store.error(stage, False)
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
                    selected_ids = set(selected.course)
                    rows = [row for row in rows if row['id'] in selected_ids]
                    if len(rows) != len(selected_ids): raise Stop('selected_course_not_in_catalog')
                if selected.review_only:
                    review_ids = {row[0] for row in store.db.execute("SELECT id FROM courses WHERE state='review'")}
                    rows = [row for row in rows if row['id'] in review_ids]
                rows = [row for row in rows if row['id'] >= selected.from_course]
                if selected.limit: rows = rows[:selected.limit]
                if selected.review_only and not rows:
                    emit({'status': 'nothing_to_review'}); return 0
                if selected.audio_stage_only:
                    from audio_stage_client import stage_audio
                    def audio_progress(event):
                        store.event('audio', None, None, 'audio_staged')
                        emit(event)
                    stage_audio(store, audio_progress)
                    store.error('audio', False)
                    emit({'status': 'audio_stage_finished'})
                    return 0
                if not selected.collect_only:
                    import importer
                    client = importer.MCPClient(workspace=ROOT)
                    target = importer.Importer(client)
                    from assets import AssetCache
                    assets = AssetCache(DATA / 'assets')
                def record_target_event(event):
                    if (not isinstance(event, dict) or set(event) != {'course_id', 'lesson_id', 'status'} or
                            event['status'] not in ('write_started', 'created')):
                        raise Stop('unsafe_target_journal_event')
                    cid, lid = int(event['course_id']), int(event['lesson_id'])
                    store.event('import', cid, lid, 'lesson_' + event['status'])
                    if event['status'] == 'created':
                        emit({'course': cid, 'lesson': lid, 'status': 'lesson_created'})
                if selected.covers_only:
                    if selected.collect_only or not client:
                        raise Stop('conflicting_mode')
                    transfer_covers(store, rows, client, assets, selected.apply)
                    emit({'status': 'covers_finished'}); return 0
                if selected.settings_only:
                    transfer_settings(store, rows, client, selected.apply)
                    emit({'status': 'settings_finished'}); return 0
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
                        if selected.collect_only:
                            store.mark(cid, 'empty'); emit({'course': cid, 'status': 'empty'}); continue
                        try:
                            from course_metadata import ensure_empty_course
                            result = ensure_empty_course(client, store.completed_snapshot(cid), apply=selected.apply)
                            store.error('import', False)
                            store.mark(cid, 'imported' if selected.apply else 'empty')
                            store.event('import', cid, None, 'empty_' + result['status'])
                            emit({'course': cid, 'status': 'empty_' + result['status'], 'lessons': 0})
                        except importer.Review as exc:
                            store.mark(cid, 'review'); store.event('import', cid, None, 'review', [str(exc)])
                            emit({'course': cid, 'status': 'review', 'stage': 'empty_import'})
                            if store.error('import', True) >= MAX_ERRORS: raise Stop('paused_after_ten_import_problems')
                        continue
                    if selected.collect_only:
                        emit({'course': cid, 'status': 'collected', 'lessons': len(payloads)}); continue
                    try:
                        payloads, normalization_warnings = prepare_payloads(payloads)
                        result = target.import_course(payloads, apply=selected.apply, images_for_lesson=assets.lesson_images,
                                                      progress_callback=record_target_event)
                        if selected.apply:
                            from settings import ensure_private_course
                            ensure_private_course(client, cid, apply=True)
                        store.error('import', False)
                        store.mark(cid, 'imported' if selected.apply or result['status'] == 'already_present' else 'collected')
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
            if selected.apply and not selected.collect_only:
                transfer_covers(store, rows, client, assets, True)
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
            reason = getattr(exc, 'reason', None) if isinstance(exc, importer.Stop) else None
            result, codes = {'status': 'stopped', 'code': code}, [code]
            if isinstance(reason, str) and importer.DIAGNOSTIC.fullmatch(reason) and reason != code:
                codes.append(reason); result['reason'] = reason
            store.event('import', None, None, 'stopped', codes); emit(result); return 1
        finally:
            store.report()
            if assets: assets.close()
            if client: client.close()


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (Stop, StorageError) as exc:
        code = str(exc) if re.fullmatch('[a-z0-9_]{1,100}', str(exc)) else 'migration_stopped'
        emit({'status': 'stopped', 'code': code})
        raise SystemExit(1) from None

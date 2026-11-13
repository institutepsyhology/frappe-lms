"""Repeatable offline MV triage: bounded read-only snapshots, never an import."""
from contextlib import closing
from datetime import datetime, timezone
import argparse
import base64
import collections
import hashlib
import json
from pathlib import Path
import re
import sqlite3

import assets
from importer import ACCOUNT, ORIGIN, SITE, Review
from normalize_audio import _receipt
from normalize_editor_nodes import _core
from normalize_source import normalize_payload
from storage import _unpack, StorageError
from lesson_policy import CODE as DEFERRED_CODE, EXCLUDED_CODE, deferred_ids, excluded_ids

DEFAULT = Path(__file__).resolve().parents[3] / 'exports/lesson-content/mastervision-migration'
FATAL = {'normalization_account_mismatch', 'normalization_metadata_conflict', 'normalization_source_invalid',
         'static_presentation_material_mismatch', 'keyboard_markup_material_mismatch',
         'redundant_link_material_mismatch', 'legacy_html_decoration_material_mismatch',
         'owner_media_account_mismatch', 'inline_image_content_mismatch',
         'owner_material_account_mismatch', 'owner_material_signature_mismatch',
         'image_wrapper_material_mismatch', 'image_wrapper_source_invalid',
         'annotated_material_button_material_mismatch',
         'reviewed_static_material_mismatch', 'reviewed_static_source_invalid',
         'missing_course_image_material_mismatch', 'missing_course_image_source_invalid',
         'reviewed_rotation_material_mismatch', 'reviewed_rotation_source_invalid',
         'reviewed_rotation_account_mismatch'}
# Historical evidence, not a claim of a fresh HTTP check. Never silently retry.
KNOWN_404 = {(280, 1802): 'fc93e347a1ef59ba7b9b32601c74cb670ee69f34403eea8f854f11768224aab8',
             (286, 1857): 'fc93e347a1ef59ba7b9b32601c74cb670ee69f34403eea8f854f11768224aab8'}


class AuditError(ValueError):
    pass


def _code(value):
    return value if isinstance(value, str) and re.fullmatch('[a-z0-9_]{1,100}', value) else 'offline_plan_failed'


def _open(directory):
    return closing(sqlite3.connect((directory / 'mastervision-migration.sqlite').as_uri() + '?mode=ro', uri=True, timeout=5))


def _inventory(directory):
    with _open(directory) as db:
        db.row_factory = sqlite3.Row
        if [tuple(r) for r in db.execute('SELECT account,origin,site FROM meta').fetchall()] != [(ACCOUNT, ORIGIN, SITE)]:
            raise AuditError('audit_account_mismatch')
        rows = db.execute("SELECT c.id,c.state,c.lesson_ids,c.source_digest,p.course_digest,p.lesson_digests FROM courses c LEFT JOIN course_checkpoints p ON p.course=c.id WHERE c.state NOT IN ('imported','excluded') ORDER BY c.id").fetchall()
        if any(r['state'] not in {'pending','review','partial','collected','empty'} for r in rows):
            raise AuditError('audit_state_invalid')
        courses = [{'id':r['id'],'state':r['state'],'lesson_ids':r['lesson_ids'],'source_digest':r['source_digest']} for r in rows]
        checkpoints = {r['id']:{'course_digest':r['course_digest'],'lesson_digests':r['lesson_digests']}
                       for r in rows if r['course_digest'] is not None}
        failures = [dict(r) for r in db.execute("SELECT course,lesson,codes FROM events WHERE stage='collect' AND status='review' AND lesson IS NOT NULL ORDER BY id").fetchall()]
    return courses, checkpoints, {r['course']: r for r in failures}


def _verified(row):
    if row is None: raise AuditError('audit_checkpoint_missing')
    try: value = _unpack(row)
    except (ValueError, StorageError): raise AuditError('audit_capture_invalid') from None
    if value.get('verified') is not True or value.get('error') is not None or not isinstance(value.get('parsed'), dict):
        raise AuditError('audit_capture_unverified')
    return value['parsed']


def _course(directory, ledger, checkpoint):
    cid = ledger['id']
    pairs = json.loads(checkpoint['lesson_digests'])
    if (not isinstance(pairs, list) or any(not isinstance(p, list) or len(p) != 2 or type(p[0]) is not int
            or p[0] <= 0 or not isinstance(p[1], str) or not re.fullmatch('[a-f0-9]{64}', p[1]) for p in pairs)
            or ledger['source_digest'] != checkpoint['course_digest']
            or json.loads(ledger['lesson_ids']) != [p[0] for p in pairs]):
        raise AuditError('audit_checkpoint_invalid')
    with _open(directory) as db:
        db.row_factory = sqlite3.Row
        row = db.execute("SELECT payload,digest FROM captures WHERE kind='course' AND course=? AND lesson=0 AND digest=?",
                         (cid, checkpoint['course_digest'])).fetchone()
        lessons = db.execute("SELECT c.lesson,c.digest,c.payload FROM json_each(?) j JOIN captures c ON c.kind='lesson' AND c.course=? AND c.lesson=json_extract(j.value,'$[0]') AND c.digest=json_extract(j.value,'$[1]')",
                             (checkpoint['lesson_digests'], cid)).fetchall()
    # All decompression, validation, and normalization happen after close().
    course = _verified(row)
    if (type(course.get('course_id')) is not int or course['course_id'] != cid
            or not isinstance(course.get('title'), str) or not course['title'].strip()
            or course.get('lesson_ids') != [p[0] for p in pairs]
            or not isinstance(course.get('lessons'), list) or len(course['lessons']) != len(pairs)
            or any(not isinstance(row, dict) or type(row.get('id')) is not int or row['id'] != lid
                   or not isinstance(row.get('title'), str) or not row['title'].strip()
                   for row, (lid, _) in zip(course['lessons'], pairs))
            or len(lessons) != len(pairs) or len({p[0] for p in pairs}) != len(pairs)):
        raise AuditError('audit_checkpoint_invalid')
    by_key = {(r['lesson'], r['digest']): r for r in lessons}
    if set(by_key) != {(lid, digest) for lid, digest in pairs}: raise AuditError('audit_checkpoint_invalid')
    return course, pairs, by_key


def _audio(directory, supplied):
    if supplied is None:
        path = directory / 'audio-files-index.json'
        if not path.exists(): return None
        if path.is_symlink() or path.stat().st_size > 1024 * 1024: raise AuditError('audit_audio_index_invalid')
        value = json.loads(path.read_bytes())
        if (not isinstance(value, dict) or set(value) != {'version','account','origin','site','files'}
                or type(value['version']) is not int or value['version'] != 1
                or (value['account'], value['origin'], value['site']) != (ACCOUNT, ORIGIN, SITE)):
            raise AuditError('audit_audio_index_invalid')
        supplied = value['files']
    if not isinstance(supplied, dict): raise AuditError('audit_audio_index_invalid')
    for key in supplied:
        if not isinstance(key, str) or not re.fullmatch('[a-f0-9]{64}', key): raise AuditError('audit_audio_index_invalid')
        try: _receipt(supplied, key)
        except Review: raise AuditError('audit_audio_index_invalid') from None
    return supplied


def _nodes(ape):
    pending = [(ape, 0)]; visited = 0
    while pending:
        node, depth = pending.pop(); visited += 1
        if (visited > 250000 or depth > 128 or not isinstance(node, dict) or not isinstance(node.get('name'), str)
                or not isinstance(node.get('fields', {}), dict) or not isinstance(node.get('children', []), list)):
            raise Review('asset_ape_invalid')
        yield node
        pending.extend((child, depth + 1) for child in reversed(node.get('children', [])))


def _images(ape):
    prepared = {}
    for node in _nodes(ape):
        if node['name'] != 'image' or assets._placeholder(node): continue
        key = node.get('id')
        if not isinstance(key, str) or not assets.IMAGE_KEY.fullmatch(key) or key in prepared:
            raise Review('asset_image_key_invalid')
        if len(prepared) >= assets.MAX_IMAGES: raise Review('asset_too_many_images')
        source = assets._image_source(node['fields'].get('imageSrc'))
        target = '/private/files/offline-image.png'
        if source.startswith('data:'):
            mime, encoded = assets._data_image(source); raw = base64.b64decode(encoded, validate=True)
            target = '/private/files/avo-' + hashlib.sha256(raw).hexdigest() + '.' + assets.DATA_MIMES[mime]
        prepared[key] = target
    return prepared


def _known_media_error(cid, lid, original, prepared):
    expected = KNOWN_404.get((cid, lid)); children = original.get('children', [])
    if expected is None or len(children) <= 7: return False
    node = children[7]
    def matches(item):
        source = item.get('fields', {}).get('imageSrc')
        return (item.get('name') == 'image' and isinstance(source, str)
                and hashlib.sha256(source.encode()).hexdigest() == expected)
    return matches(node) and any(matches(item) for item in _nodes(prepared))


def audit_remaining(directory, audio_assets=None, progress=None):
    """Return IDs/codes/counts only. Assets are shape-checked, never fetched.

    The source reader closes before each course is parsed. At most one course's
    compressed captures and one decoded lesson remain in memory. Historical
    404 evidence is separate from structural readiness and unverified media.
    """
    if (ACCOUNT, ORIGIN, SITE) != ('mastervision', 'https://shop.mastervision.su', 'my-lk.mastervision.su'):
        raise AuditError('audit_account_mismatch')
    directory = Path(directory).resolve()
    courses, checkpoints, failures = _inventory(directory)
    audio = _audio(directory, audio_assets)
    results = []; counts = collections.Counter(); affected = collections.defaultdict(set)
    for ledger in courses:
        cid = ledger['id']
        if type(cid) is not int or cid <= 0: raise AuditError('audit_checkpoint_invalid')
        result = {'course_id': cid, 'state': ledger['state'], 'lesson_ids': [], 'planned_lesson_ids': [],
                  'known_excluded': [], 'deferred_lesson_ids': [], 'ready_lessons': 0, 'uses_audio': False,
                  'audio_keys': [], 'images': 0, 'issues': [], 'known_asset_errors': [], 'normalization_reviews': []}
        checkpoint = checkpoints.get(cid)
        if checkpoint is None:
            failure = failures.get(cid, {}); codes = [_code(c) for c in json.loads(failure.get('codes', '["completed_course_checkpoint_missing"]'))]
            result['collection_failure'] = {'lesson_id': failure.get('lesson'), 'codes': codes}
        else:
            course, pairs, rows = _course(directory, ledger, checkpoint); audio_keys = set()
            for source_lesson, (lid, digest) in zip(course['lessons'], pairs):
                payload = _verified(rows[(lid, digest)]).get('payload')
                if (not isinstance(payload, dict) or (payload.get('account'), payload.get('source_origin')) != (ACCOUNT, ORIGIN)
                        or type(payload.get('course_id')) is not int or payload['course_id'] != cid
                        or type(payload.get('lesson_id')) is not int or payload['lesson_id'] != lid
                        or source_lesson.get('id') != lid or payload.get('course_title') != course['title']
                        or payload.get('lesson_title') != source_lesson.get('title') or payload.get('format') != 'ape'):
                    raise AuditError('audit_checkpoint_invalid')
                if not isinstance(payload.get('ape'), dict): raise AuditError('audit_checkpoint_invalid')
                result['lesson_ids'].append(lid); review = None
                if lid in excluded_ids(cid):
                    result['known_excluded'].append({'lesson_id':lid, 'code':EXCLUDED_CODE})
                    del payload
                    continue
                if lid in deferred_ids(cid):
                    result['deferred_lesson_ids'].append(lid)
                    result['issues'].append({'lesson_id':lid, 'codes':[DEFERRED_CODE]})
                    del payload
                    continue
                result['planned_lesson_ids'].append(lid)
                try: prepared, _ = normalize_payload(payload, audio_assets=audio)
                except Review as exc:
                    review = _code(str(exc))
                    if review in FATAL: raise AuditError(review) from None
                    result['normalization_reviews'].append({'lesson_id':lid, 'code':review})
                    prepared = payload  # The exact run.prepare_payloads fallback.
                for node in _nodes(payload['ape']):
                    if node['name'] == 'audio':
                        result['uses_audio'] = True; source = node['fields'].get('audioSrc')
                        if isinstance(source, str): audio_keys.add(hashlib.sha256(source.encode()).hexdigest())
                result['images'] += sum(n['name'] == 'image' and not assets._placeholder(n) for n in _nodes(prepared['ape']))
                try:
                    images = _images(prepared['ape'])
                    issues = [_code(c) for c in _core().plan_import(prepared, image_urls=images)['issues']]
                except (Review, ValueError) as exc: issues = [_code(str(exc))]
                if issues:
                    item = {'lesson_id': lid, 'codes': list(dict.fromkeys(issues))}
                    if review: item['normalization_review'] = review
                    result['issues'].append(item)
                else: result['ready_lessons'] += 1
                if _known_media_error(cid, lid, payload['ape'], prepared['ape']):
                    result['known_asset_errors'].append({'lesson_id': lid, 'code': 'known_prior_asset_404'})
                del payload, prepared
            result['audio_keys'] = sorted(audio_keys)
            del course, rows
        result['pure_ready'] = checkpoint is not None and not result['issues']
        result['media_availability'] = 'known_prior_404' if result['known_asset_errors'] else 'unverified'
        result['candidate_for_media_preflight'] = result['pure_ready'] and not result['known_asset_errors']
        for issue in result['issues'] + ([result['collection_failure']] if 'collection_failure' in result else []):
            for code in issue['codes']: counts[code] += 1; affected[code].add(cid)
        results.append(result)
        if progress: progress({'status':'course_audited','course_id':cid,'lessons':len(result['lesson_ids']),
                               'ready_lessons':result['ready_lessons'],'pure_ready':result['pure_ready'],
                               'known_asset_errors':len(result['known_asset_errors'])})
    report = {'version':1,'account':ACCOUNT,'origin':ORIGIN,'site':SITE,'mode':'offline',
              'created_at_utc':datetime.now(timezone.utc).isoformat(), 'courses':results,
              'issue_counts':[{'code':code,'lessons':n,'courses':len(affected[code])} for code,n in counts.most_common()],
              'summary':{'review_courses':len(results),'remaining_courses':len(results),
                         'state_counts':dict(collections.Counter(r['state'] for r in results)),
                         'lessons':sum(len(r['lesson_ids']) for r in results),
                         'partial_courses':sum(r['state'] == 'partial' for r in results),
                         'deferred_lessons':sum(len(r['deferred_lesson_ids']) for r in results),
                         'known_excluded_lessons':sum(len(r['known_excluded']) for r in results),
                         'planned_lessons':sum(len(r['planned_lesson_ids']) for r in results),
                         'pure_ready_courses':sum(r['pure_ready'] for r in results),
                         'normalization_reviews':sum(len(r['normalization_reviews']) for r in results),
                         'collection_failures':sum('collection_failure' in r for r in results),
                         'known_media_blocked_courses':sum(bool(r['known_asset_errors']) for r in results)},
              'limits':['no_network_or_target_preflight','media_availability_unverified','known_404_is_historical_evidence']}
    if progress: progress({'status':'completed', **report['summary']})
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--directory', type=Path, default=DEFAULT)
    parser.add_argument('--output', action='store_true', help='Save private remaining-audit.json beside the archive')
    args = parser.parse_args()
    try:
        report = audit_remaining(args.directory, progress=lambda row: print(json.dumps(row), flush=True))
        if args.output:
            from audio_stage_client import _save_index
            _save_index(args.directory.resolve() / 'remaining-audit.json', report)
    except Exception:
        print(json.dumps({'status':'failed','code':'offline_audit_failed'}), flush=True)
        raise SystemExit(1)

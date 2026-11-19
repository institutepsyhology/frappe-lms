"""Verify and import one complete capture as an unpublished IOMP course."""

import base64
from contextlib import closing
import hashlib
import json
from pathlib import Path
import re
import sys
import urllib.error
import urllib.request
from urllib.parse import urljoin, urlsplit


EXPERIMENTS = Path(__file__).resolve().parents[1]
REPOSITORY = EXPERIMENTS.parent
WORKSPACE = REPOSITORY.parent
ARCHIVE = WORKSPACE / 'exports/lesson-content/iomp/captured'
sys.path[:0] = [str(EXPERIMENTS / 'mastervision-migration'), str(REPOSITORY)]
from assets import MAX_IMAGE, MAX_IMAGES, NoRedirect, _data_image, _inspect
from covers import _local_public_url
from importer import DIAGNOSTIC, IOMP_BINDING, Importer, MCPClient, Review, Stop, source_id
from lms.lms.avo_transform import IMAGE_KEY, omit_placeholder_node, omit_placeholder_section, plan_import
from normalize_review import EXCLUDED_LESSONS, normalize_review
from normalize_iomp_material import normalize_iomp_material, reviewed_image_url
from normalize_iomp_course_material import normalize_iomp_course_material
from normalize_reviewed_pairs import normalize_reviewed_pairs
from normalize_life_position import normalize_life_position
from normalize_reviewed_vk import normalize_reviewed_vk
from jpeg_cover import prepare_jpeg_upload
from course_audio import prepare_course_audio, sync_course_audio
from shared_course_audio import prepare_shared_audio, verify_shared_audio, verify_shared_destination


ACCOUNT, ORIGIN, SITE, SERVER = IOMP_BINDING


class IompClient(MCPClient):
    account, origin, site, server_name = IOMP_BINDING


class IompImporter(Importer):
    account, origin, site = IOMP_BINDING[:3]


class Course60Importer(IompImporter):
    """Keep the existing draft 345 in its source position across all import checks."""

    def __init__(self, client, source_ids):
        super().__init__(client)
        self.source_order = [lid for lid in map(str, source_ids) if lid == '345' or lid not in EXCLUDED_LESSONS]
        initial = super().outline('60')
        self.retained_name = initial['by_id'].get('345', {}).get('name')

    def outline(self, course_id):
        outline = super().outline(course_id)
        if course_id != '60':
            return outline
        draft_name = outline['by_id'].get('345', {}).get('name')
        if draft_name != self.retained_name:
            raise Review('course_order_conflict')
        if not draft_name:
            return outline
        ids = outline['ids']
        if ids != self.source_order[:len(ids)]:
            raise Review('course_order_conflict')
        return {**outline, 'ids': [lid for lid in ids if lid != '345'],
                'by_id': {lid: row for lid, row in outline['by_id'].items() if lid != '345'},
                'retained_lesson_ids': ['345']}


def fetch_image(value):
    if not isinstance(value, str) or not value:
        raise Review('asset_url_invalid')
    if value.startswith('data:'):
        mime, encoded = _data_image(value)
        raw = base64.b64decode(encoded, validate=True)
        return raw, _inspect(raw, mime)
    url = urlsplit(urljoin(ORIGIN, value))
    host = url.hostname or ''
    ordinary_image = (not url.query and not url.fragment
                      and (host == 'shop.iomp.ru' or re.fullmatch(r'f[0-9]+\.autoweboffice\.(?:ru|com)', host))
                      and re.search(r'\.(?:png|jpe?g|webp)$', url.path, re.I))
    if url.scheme != 'https' or url.netloc != host or not (ordinary_image or reviewed_image_url(url.geturl())):
        raise Review('asset_host_requires_review')
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    try:
        with opener.open(url.geturl(), timeout=20) as response:
            if response.status != 200 or response.geturl() != url.geturl():
                raise Review('asset_response_invalid')
            raw = response.read(MAX_IMAGE + 1)
            return raw, _inspect(raw, response.headers.get('Content-Type', ''))
    except urllib.error.HTTPError as error:
        raise Review('asset_not_found' if error.code == 404 else 'asset_unavailable') from None
    except (urllib.error.URLError, OSError):
        raise Review('asset_unavailable') from None


def lesson_images(payload):
    course, lesson = map(source_id, (payload['course_id'], payload['lesson_id']))
    if (payload.get('account'), payload.get('source_origin')) != (ACCOUNT, ORIGIN):
        raise Stop('source_account_mismatch')
    images, pending = {}, [payload['ape']]
    while pending:
        node = pending.pop()
        if omit_placeholder_node(node, ACCOUNT, course, lesson) or omit_placeholder_section(node, ACCOUNT, course, lesson):
            continue
        pending.extend(reversed(node.get('children', [])))
        if node.get('name') == 'image':
            key = node.get('id')
            if not isinstance(key, str) or not IMAGE_KEY.fullmatch(key) or key in images or len(images) >= MAX_IMAGES:
                raise Review('asset_image_key_invalid')
            raw, _ = fetch_image(node.get('fields', {}).get('imageSrc'))
            images[key] = base64.b64encode(raw).decode('ascii')
    return images


def normalize_avatar_label(payload):
    """Recognize the labelled variant of the standard AVO avatar in IOMP."""
    course, lesson = payload['course_id'], payload['lesson_id']
    pending = [payload['ape']]
    while pending:
        node = pending.pop()
        pending.extend(node.get('children', []))
        fields = node.get('fields', {})
        if node.get('name') != 'image' or fields.get('html') != 'Изображение':
            continue
        candidate_fields = {key: value for key, value in fields.items() if key != 'html'}
        if omit_placeholder_node({**node, 'fields': candidate_fields}, ACCOUNT, course, lesson):
            node['fields'] = candidate_fields


def refreshed_lessons(path, course_id, lesson_ids):
    refreshed = {}
    for receipt in sorted((path.parent / 'refreshed').glob('*/refresh-status.json')):
        # A full capture supersedes earlier partial captures, including their outlines.
        if receipt.parent.name < path.name:
            continue
        row = json.loads(receipt.read_text(encoding='utf-8'))
        if (row.get('account'), row.get('course_id'), row.get('lesson_ids')) != (ACCOUNT, int(course_id), lesson_ids):
            raise Stop('refreshed_outline_mismatch')
        for ident in row['refreshed']:
            if ident not in lesson_ids or type(ident) is not int:
                raise Stop('refreshed_lesson_mismatch')
            refreshed[str(ident)] = receipt.parent / f'lesson-{ident}.json'
    return refreshed


def read_capture(directory):
    path = Path(directory).resolve(strict=True)
    if not path.is_relative_to(ARCHIVE.resolve(strict=True)):
        raise Stop('capture_directory_invalid')
    status = json.loads((path / 'capture-status.json').read_text(encoding='utf-8'))
    meta = json.loads((path / 'course.json').read_text(encoding='utf-8'))
    cid = source_id(status['course_id'])
    ids = status['lesson_ids']
    include = [str(value) for value in ids]
    if (status.get('account') != ACCOUNT or path.parent.name != f'course-{cid}' or
            status.get('outline_verified') is not True or status.get('issues') or
            status['saved'] != ids or meta['course_id'] != int(cid) or meta['lesson_ids'] != ids or
            len(set(include)) != len(ids) or any(source_id(value) != value for value in include)):
        raise Stop('capture_incomplete')
    refreshed = refreshed_lessons(path, cid, ids)
    records = []
    for ident in include:
        if ident in EXCLUDED_LESSONS:
            continue
        document = refreshed.get(ident, path / f'lesson-{ident}.json')
        lesson = json.loads(document.read_text(encoding='utf-8'))
        payload = lesson['payload']
        if (payload['account'], payload['source_origin'], source_id(payload['course_id']),
                source_id(payload['lesson_id']), payload['course_title']) != (ACCOUNT, ORIGIN, cid, ident, meta['title']):
            raise Stop('source_account_mismatch')
        payload.update(course_id=cid, lesson_id=ident)
        if payload['format'] == 'ape':
            normalize_reviewed_pairs(payload, ARCHIVE)
            normalize_avatar_label(payload)
            normalize_reviewed_vk(payload)
            normalize_review(payload)
            normalize_iomp_material(payload)
            normalize_iomp_course_material(payload)
            normalize_life_position(payload, ARCHIVE, presentation='powerpoint')
        records.append(payload)
    return cid, meta, records


def mutate(client, name, arguments):
    result = client.rpc('tools/call', {'name': name, 'arguments': arguments})
    value = result.get('structuredContent')
    if result.get('isError') or not isinstance(value, dict):
        raise Stop('course_metadata_write_uncertain')
    return value


def checked_course(client, name, cid):
    course = client.call('get_document', {'doctype': 'LMS Course', 'name': name})
    if (course.get('name'), course.get('custom_avo_id'), course.get('custom_lms_id'),
            course.get('custom_avo_account'), course.get('published')) != (name, cid, cid, ACCOUNT, 0):
        raise Stop('course_identity_invalid')
    return course


def cover_file(client, name, cid, raw, extension, digest):
    filename = f'avo-iomp-course-{cid}-{digest[:16]}.{extension}'
    filters = [['attached_to_doctype', '=', 'LMS Course'], ['attached_to_name', '=', name],
               ['attached_to_field', '=', 'image'], ['file_name', '=', filename]]
    rows = client.call('list_documents', {'doctype': 'File', 'fields': ['name'], 'filters': filters, 'limit': 2})
    if rows.get('has_next_page') or len(rows['documents']) > 1:
        raise Stop('cover_file_ambiguous')
    if rows['documents']:
        file_name = rows['documents'][0]['name']
    else:
        file = mutate(client, 'create_document', {'doctype': 'File', 'data': {
            'file_name': filename, 'content': base64.b64encode(raw).decode('ascii'), 'decode': 1, 'is_private': 0,
            'attached_to_doctype': 'LMS Course', 'attached_to_name': name, 'attached_to_field': 'image',
        }})
        file_name = file['name']
    file = client.call('get_document', {'doctype': 'File', 'name': file_name})
    url = file.get('file_url', '')
    if (file.get('attached_to_doctype'), file.get('attached_to_name'), file.get('attached_to_field'),
            file.get('is_private'), file.get('file_size'), file.get('content_hash')) != (
            'LMS Course', name, 'image', 0, len(raw), hashlib.md5(raw).hexdigest()
    ) or file.get('file_name') != filename or not _local_public_url(url):
        raise Stop('cover_file_readback_invalid')
    return url


def finish_course(client, name, cid, cover):
    before = checked_course(client, name, cid)
    updates = {}
    cover_issue = None
    if not before.get('image') and cover:
        try:
            raw, extension = fetch_image(cover)
            digest = hashlib.sha256(raw).hexdigest()
            if extension == 'jpg':
                raw = prepare_jpeg_upload(raw)
        except Review as error:
            cover_issue = diagnostic(error)
        else:
            updates['image'] = cover_file(client, name, cid, raw, extension, digest)
    if before.get('disable_self_learning') != 1:
        updates['disable_self_learning'] = 1
    if updates:
        current = checked_course(client, name, cid)
        if current.get('modified') != before.get('modified') or not current.get('modified'):
            raise Stop('course_changed_during_import')
        mutate(client, 'update_document', {'doctype': 'LMS Course', 'name': name,
               'data': {**updates, 'modified': current['modified']}})
    final = checked_course(client, name, cid)
    if final.get('disable_self_learning') != 1 or any(final.get(field) != value for field, value in updates.items()):
        raise Stop('course_metadata_readback_invalid')
    return {'cover': bool(final.get('image')), 'cover_issue': cover_issue}


def diagnostic(error):
    return str(error) if DIAGNOSTIC.fullmatch(str(error)) else 'operation_failed'


def preflight_source(payloads):
    problems = []
    for payload in payloads:
        try:
            issues = [code for code in plan_import(payload, {})['issues'] if code != 'image_not_prepared']
        except (TypeError, ValueError):
            issues = ['source_converter_input_invalid']
        if issues:
            problems.append({'lesson_id': payload['lesson_id'], 'codes': issues})
    if problems:
        raise Review('course_needs_review', problems)


def verify_empty_destination(client, cid, lesson_ids):
    checks = [('LMS Course', {'custom_avo_account': ACCOUNT, 'custom_avo_id': cid}),
              ('File', {'file_name': ['like', f'avo-iomp-course-{cid}-%']}),
              ('File', {'file_name': ['like', f'avo-iomp-{cid}-%']})]
    for offset in range(0, len(lesson_ids), 100):
        checks.append(('Course Lesson', {'custom_avo_account': ACCOUNT,
                      'custom_avo_id': ['in', lesson_ids[offset:offset + 100]]}))
    for doctype, filters in checks:
        result = client.call('list_documents', {'doctype': doctype, 'fields': ['name'], 'filters': filters, 'limit': 1})
        if result.get('documents') != [] or result.get('has_next_page') is not False:
            raise Stop('course_prior_write_requires_reconciliation')


def main(directory, *, defer_final_lesson=None, require_empty=False, client_scope=None):
    cid = None
    try:
        course_dir = Path(directory).resolve().parent
        if course_dir.parent == ARCHIVE.resolve() and re.fullmatch(r'course-[1-9][0-9]{0,9}', course_dir.name):
            cid = course_dir.name.removeprefix('course-')
        cid, meta, payloads = read_capture(directory)
        excluded = [str(ident) for ident in meta['lesson_ids'] if str(ident) in EXCLUDED_LESSONS]
        if not payloads:
            if excluded:
                return {'status': 'excluded', 'course_id': cid, 'excluded_lesson_ids': excluded}
            raise Review('empty_source_course')
        audio = prepare_course_audio(payloads)
        shared_audio = prepare_shared_audio(payloads)
        deferred = []
        try:
            preflight_source(payloads)
        except Review as error:
            if (len(payloads) < 2 or payloads[-1]['lesson_id'] != defer_final_lesson
                    or len(error.problems) != 1 or error.problems[0]['lesson_id'] != defer_final_lesson
                    or 'empty_lesson' not in error.problems[0]['codes']):
                raise
            deferred = error.problems
            payloads = payloads[:-1]
        with (client_scope() if client_scope is not None else closing(IompClient(WORKSPACE))) as client:
            if require_empty:
                verify_empty_destination(client, cid, [str(i) for i in meta['lesson_ids']])
            if cid == '60' and '345' in excluded:
                importer = Course60Importer(client, meta['lesson_ids'])
            else:
                importer = IompImporter(client)
            sync_course_audio('prepare', audio)
            verify_shared_audio(importer, shared_audio)
            report = importer.import_course(payloads, apply=True, images_for_lesson=lesson_images)
            outcome = importer.outline(cid)
            sync_course_audio('attach', audio)
            verify_shared_destination(importer, shared_audio)
            metadata = finish_course(client, outcome['course'], cid, meta['cover_url'])
            retained = outcome.get('retained_lesson_ids', [])
            result = {'status': 'imported', 'course_id': cid, 'lessons': len(outcome['ids']) + len(retained),
                      'created': len(report['created_lesson_ids']), 'warnings': report['warnings'],
                      'excluded_lesson_ids': excluded, **metadata}
            if retained:
                result['retained_lesson_ids'] = retained
            if audio:
                result['verified_audio_files'] = len(audio)
            if shared_audio:
                result['reused_audio_files'] = sum(map(len, shared_audio.values()))
            if deferred:
                result.update(status='review', code='final_lesson_deferred', issues=deferred)
            return result
    except Review as error:
        return {'status': 'review', 'course_id': cid, 'code': diagnostic(error), 'issues': error.problems}
    except Exception as error:
        return {'status': 'stopped', 'course_id': cid, 'code': diagnostic(error),
                'write_reason': getattr(error, 'reason', None)}


if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument('directory')
    parser.add_argument('--defer-final-lesson', help='ID of a known empty final lesson to leave for review')
    parser.add_argument('--require-empty', action='store_true')
    args = parser.parse_args()
    print(json.dumps({'account': ACCOUNT, **main(args.directory, defer_final_lesson=args.defer_final_lesson,
                                                require_empty=args.require_empty)},
                     ensure_ascii=True))

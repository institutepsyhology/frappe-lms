"""Reuse course 91's verified private IOMP recordings in matching IOMP lessons."""
import copy
import hashlib
from html.parser import HTMLParser
import json
import re

from course_audio import prepare_course_audio
from course_audio_worker import target, MAX_SIZE
from importer import IOMP_BINDING, Review, Stop


# Pairing was checked against both sets of captures. Each list of audio paths is in source order.
PAIRED = {str(lesson): str(lesson - 67) for lesson in range(1896, 1906)}
COURSE_PAIRS = {'116': PAIRED, '333': {str(lesson): str(lesson - 4447) for lesson in range(6276, 6286)}}
ORDERED_MANIFEST = '4c7e8f98d57c79095be0aba4b447d4272bdcffafa4e84094630e5711fdea04ef'
PREFIX = '/private/files/avo-iomp-91-'
ORIGIN = 'https://' + IOMP_BINDING[2]


def prepare_shared_audio(payloads):
    """Prepare copies of leaf nodes. Course/lesson IDs in the imported documents stay original."""
    course = next((p.get('course_id') for p in payloads if p.get('course_id') in COURSE_PAIRS
                   and p.get('account') == 'iomp'), None)
    if not course:
        return {}
    pairs = COURSE_PAIRS[course]
    if any((p.get('account'), p.get('source_origin'), p.get('course_id')) !=
           (*IOMP_BINDING[:2], course) for p in payloads):
        raise Stop('source_account_mismatch')
    originals = [p for p in payloads if p.get('lesson_id') in pairs]
    if len(originals) != len(pairs) or {p['lesson_id'] for p in originals} != set(pairs):
        raise Review('iomp_shared_audio_source_changed')
    shadow = [{**p, 'course_id': '91', 'lesson_id': pairs[p['lesson_id']], 'ape': copy.deepcopy(p['ape'])}
              for p in originals]
    try:
        rows = prepare_course_audio(shadow, alternate_player=(course == '333'))
    except Review as error:
        source_to_target = {v: k for k, v in pairs.items()}
        problems = [{**p, 'lesson_id': source_to_target.get(p.get('lesson_id'), p.get('lesson_id'))}
                    for p in error.problems]
        raise Review(str(error), problems) from None
    paths = {}
    for row in rows:
        paths.setdefault(row['lesson_id'], []).append(target(row))
    check_order(paths)
    for original, prepared in zip(originals, shadow):
        original['ape'] = prepared['ape']
    return paths


def check_order(paths):
    encoded = json.dumps(paths, sort_keys=True, separators=(',', ':')).encode()
    if hashlib.sha256(encoded).hexdigest() != ORDERED_MANIFEST:
        raise Review('iomp_shared_audio_source_order_changed')


class AudioLinks(HTMLParser):
    def __init__(self):
        super().__init__()
        self.hrefs = []

    def handle_starttag(self, tag, attrs):
        if tag == 'a':
            self.hrefs.extend(v for k, v in attrs if k == 'href' and isinstance(v, str) and PREFIX in v)


def list_rows(client, doctype, filters, fields):
    result = client.call('list_documents', {'doctype': doctype, 'filters': filters, 'fields': fields, 'limit': 100})
    rows = result.get('documents')
    if not isinstance(rows, list) or result.get('has_next_page') is not False or not all(isinstance(r, dict) for r in rows):
        raise Review('iomp_shared_audio_readback_incomplete')
    return rows


def verify_lesson_links(importer, cid, expected_paths):
    """Read actual lesson identities and ordered saved hrefs for one IOMP course."""
    client = importer.client
    if (client.account, client.origin, client.site, client.server_name) != IOMP_BINDING:
        raise Stop('wrong_frappe_site')
    outline = importer.outline(cid)
    names = {lid: outline['by_id'][lid]['name'] for lid in expected_paths if lid in outline['by_id']}
    if set(names) != set(expected_paths):
        raise Review('iomp_shared_audio_lesson_missing')
    lesson_docs = list_rows(client, 'Course Lesson', {'name': ['in', list(names.values())]},
                            ['name', 'custom_avo_id', 'custom_lms_id', 'custom_avo_account', 'course', 'content'])
    checked = set()
    for lesson in lesson_docs:
        lid = lesson.get('custom_avo_id')
        if (lid not in names or lid in checked or lesson.get('name') != names[lid] or
                (lesson.get('custom_lms_id'), lesson.get('custom_avo_account'), lesson.get('course')) !=
                (lid, IOMP_BINDING[0], outline['course'])):
            raise Review('iomp_shared_audio_lesson_mismatch')
        try:
            blocks = json.loads(lesson['content'])['blocks']
            parser = AudioLinks()
            for block in blocks:
                if block['type'] == 'paragraph':
                    parser.feed(block['data']['text'])
            parser.close()
        except (AttributeError, KeyError, TypeError, ValueError):
            raise Review('iomp_shared_audio_lesson_mismatch') from None
        if parser.hrefs != [ORIGIN + path for path in expected_paths[lid]]:
            raise Review('iomp_shared_audio_links_changed', [{'lesson_id': lid}])
        checked.add(lid)
    if checked != set(names):
        raise Review('iomp_shared_audio_lesson_missing')
    return names


def verify_shared_destination(importer, paths, course_id='116', *, included_lessons=None):
    """Check all source IDs and every saved url in the ten destination lessons."""
    if paths:
        check_order(paths)
        pairs = COURSE_PAIRS[course_id]
        targets = {dst: paths[src] for dst, src in pairs.items() if included_lessons is None or dst in included_lessons}
        if targets:
            verify_lesson_links(importer, course_id, targets)


def verify_shared_audio(importer, paths):
    """Only reads. Native LMS grant checks use the references in each lesson's saved content."""
    if not paths:
        return
    check_order(paths)
    names = verify_lesson_links(importer, '91', paths)
    client = importer.client
    expected = {path: names[lid] for lid in paths for path in paths[lid]}
    rows = list_rows(client, 'File', {'file_url': ['in', list(expected)]},
                     ['name', 'file_name', 'file_url', 'owner', 'is_private', 'is_folder', 'file_size', 'content_hash',
                      'attached_to_doctype', 'attached_to_name', 'attached_to_field'])
    seen, files, hashes = set(), set(), set()
    for f in rows:
        path, name, size, digest = f.get('file_url'), f.get('name'), f.get('file_size'), f.get('content_hash')
        if (path not in expected or path in seen or not isinstance(name, str) or not name or name in files
                or f.get('file_name') != path.rsplit('/', 1)[-1]
                or (f.get('is_private'), f.get('is_folder'), f.get('owner'), f.get('attached_to_doctype'),
                    f.get('attached_to_name'), f.get('attached_to_field')) !=
                   (1, 0, 'Administrator', 'Course Lesson', expected[path], 'content')
                or type(size) is not int or not 10 <= size <= MAX_SIZE
                or not isinstance(digest, str) or not re.fullmatch(r'[0-9a-f]{32}', digest) or digest in hashes):
            raise Review('iomp_shared_audio_file_mismatch')
        seen.add(path)
        files.add(name)
        hashes.add(digest)
    if seen != set(expected):
        raise Review('iomp_shared_audio_file_missing')
    if list_rows(client, 'DocShare', {'share_doctype': 'File', 'share_name': ['in', sorted(files)]}, ['name']):
        raise Review('iomp_shared_audio_file_shared')

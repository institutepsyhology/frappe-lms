"""Read-only postcondition for the one pinned, reused MV image and its link."""
import hashlib
import json
from html.parser import HTMLParser
import urllib.request

from importer import ACCOUNT, SITE, Stop
from normalize_reviewed_shared_image import (
    PINNED_TARGET_PATH, IMAGE_MD5, IMAGE_SIZE, IMAGE_SHA256, FILE_OWNER,
)

CODE = 'reviewed_shared_image_target_mismatch'


def _require(value):
    if not value: raise Stop(CODE)


def _rows(client, doctype, fields, filters):
    result = client.call('list_documents', {
        'doctype': doctype, 'fields': fields, 'filters': filters, 'limit': 5})
    _require(isinstance(result, dict) and result.get('has_next_page') is False)
    rows = result.get('documents')
    _require(isinstance(rows, list) and len(rows) <= 5 and all(isinstance(r, dict) for r in rows))
    return rows


class _Links(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True); self.links = []

    def handle_starttag(self, tag, attrs):
        if tag == 'a':
            _require(len(attrs) == len(dict(attrs)))
            self.links.append(dict(attrs).get('href'))


def verify_reviewed_shared_image_target(client, course_id, lesson_id):
    # No work for unrelated imports, including their synthetic test fixtures.
    if (str(course_id), str(lesson_id)) != ('634', '7364'): return None
    _require(type(course_id) in (str, int) and type(lesson_id) in (str, int))
    _require(getattr(client, 'site', None) == SITE == 'my-lk.mastervision.su'
             and getattr(client, 'account', None) == ACCOUNT == 'mastervision')
    courses = _rows(client, 'LMS Course',
        ['name', 'custom_avo_account', 'custom_avo_id', 'custom_lms_id', 'published'],
        [['custom_avo_account', '=', ACCOUNT], ['custom_avo_id', '=', '634']])
    _require(len(courses) == 1)
    course = courses[0]
    _require(course.get('custom_avo_account') == ACCOUNT and course.get('custom_avo_id') == '634'
             and course.get('custom_lms_id') == '634' and course.get('published') == 0)
    lessons = _rows(client, 'Course Lesson',
        ['name', 'course', 'custom_avo_account', 'custom_avo_id', 'custom_lms_id',
         'is_draft', 'include_in_preview', 'owner'],
        [['custom_avo_account', '=', ACCOUNT], ['custom_avo_id', '=', '7364']])
    _require(len(lessons) == 1)
    lesson = lessons[0]
    _require(lesson.get('custom_avo_account') == ACCOUNT and lesson.get('custom_avo_id') == '7364'
             and lesson.get('custom_lms_id') == '7364' and lesson.get('course') == course.get('name')
             and lesson.get('owner') == FILE_OWNER and lesson.get('is_draft') == 1
             and lesson.get('include_in_preview') == 0)
    doc = client.call('get_document', {'doctype': 'Course Lesson', 'name': lesson['name']})
    _require(isinstance(doc, dict) and all(doc.get(k) == v for k, v in lesson.items()))
    body = doc.get('body')
    _require(isinstance(body, str) and len(body.encode()) <= 1024 * 1024)
    try: blocks = json.loads(body)['blocks']
    except (ValueError, KeyError, TypeError): raise Stop(CODE) from None
    _require(isinstance(blocks, list) and len(blocks) <= 100)
    image_urls, links = [], _Links()
    for block in blocks:
        _require(isinstance(block, dict) and isinstance(block.get('data'), dict))
        data = block['data']
        if block.get('type') == 'image':
            _require(isinstance(data.get('file'), dict))
            image_urls.append(data['file'].get('url'))
        elif block.get('type') == 'paragraph':
            _require(isinstance(data.get('text'), str)); links.feed(data['text'])
    links.close()
    absolute = 'https://' + SITE + PINNED_TARGET_PATH
    _require(image_urls == [PINNED_TARGET_PATH] and links.links.count(absolute) == 1)
    files = _rows(client, 'File', ['name', 'file_name', 'file_url', 'content_hash', 'file_size',
        'is_private', 'owner', 'attached_to_doctype', 'attached_to_name', 'attached_to_field'],
        [['attached_to_doctype', '=', 'Course Lesson'], ['attached_to_name', '=', lesson['name']]])
    images = [f for f in files if f.get('file_name') == PINNED_TARGET_PATH.rsplit('/', 1)[1]]
    _require(len(images) == 1)
    image = images[0]
    _require(image.get('file_url') == PINNED_TARGET_PATH and image.get('content_hash') == IMAGE_MD5
             and type(image.get('file_size')) is int and image['file_size'] == IMAGE_SIZE
             and image.get('is_private') == 1 and image.get('owner') == FILE_OWNER
             and image.get('attached_to_doctype') == 'Course Lesson'
             and image.get('attached_to_name') == lesson['name'] and image.get('attached_to_field') == 'body')
    # The URL is a fixed same-site constant; the client's NoRedirect opener
    # prevents forwarding authentication elsewhere. Bounded read, never mutate.
    try:
        request = urllib.request.Request(absolute, headers=dict(client.auth))
        with client.opener.open(request, timeout=20) as response:
            _require(response.status == 200)
            raw = response.read(IMAGE_SIZE + 1)
    except Stop: raise
    except Exception: raise Stop('reviewed_shared_image_readback_unavailable') from None
    _require(len(raw) == IMAGE_SIZE and hashlib.md5(raw).hexdigest() == IMAGE_MD5
             and hashlib.sha256(raw).hexdigest() == IMAGE_SHA256)
    return {'course_id': '634', 'lesson_id': '7364', 'code': 'reviewed_shared_image_verified',
            'file_md5': IMAGE_MD5, 'file_size': IMAGE_SIZE, 'file_sha256': IMAGE_SHA256}

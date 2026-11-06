"""Import one AVO lesson through the existing authenticated Frappe MCP.

POST only. Source images are private attachments, and the original snapshot is
retained as a private attachment. The endpoint never grants learner access.
"""
import base64
import binascii
import hashlib
import io
import json
import warnings

import frappe
from PIL import Image
from lms.lms.avo_transform import IMAGE_KEY, plan_import, omit_placeholder_section, omit_placeholder_node

SITE_ACCOUNTS = {
    'my-lk.mv-centr.ru': ('mv-centr', 'https://shop.mv-centr.ru'),
    'my-lk.mastervision.su': ('mastervision', 'https://shop.mastervision.su'),
    'my-lk.iomp.ru': ('iomp', 'https://shop.iomp.ru'),
}
MAX_IMAGE = 5 * 1024 * 1024
MAX_IMAGES = 10
EXTENSIONS = {'PNG': 'png', 'JPEG': 'jpg', 'WEBP': 'webp'}


def _images(images):
    if images is None:
        return {}
    if not isinstance(images, dict) or len(images) > MAX_IMAGES:
        raise ValueError('invalid_images')
    result = {}
    for key, encoded in images.items():
        if not isinstance(key, str) or not IMAGE_KEY.fullmatch(key) or not isinstance(encoded, str):
            raise ValueError('invalid_image')
        if len(encoded) > ((MAX_IMAGE + 2) // 3) * 4:
            raise ValueError('image_too_large')
        try:
            raw = base64.b64decode(encoded, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise ValueError('invalid_image_encoding') from exc
        if not raw or len(raw) > MAX_IMAGE:
            raise ValueError('image_size_invalid')
        try:
            with warnings.catch_warnings():
                warnings.simplefilter('error', Image.DecompressionBombWarning)
                with Image.open(io.BytesIO(raw)) as img:
                    fmt = img.format
                    width, height = img.size
                    if fmt not in EXTENSIONS or width < 1 or height < 1 or width > 4096 or height > 4096:
                        raise ValueError('image_format_invalid')
                    img.verify()
        except Exception as exc:
            raise ValueError('image_invalid') from exc
        digest = hashlib.sha256(raw).hexdigest()
        result[key] = {'bytes': raw, 'sha256': digest, 'name': 'avo-' + digest + '.' + EXTENSIONS[fmt]}
    return result


def _schema():
    for doctype in ('LMS Course', 'Course Lesson'):
        meta = frappe.get_meta(doctype)
        fields = ['custom_avo_account', 'custom_avo_id']
        if any(not meta.has_field(field) for field in fields):
            raise ValueError('mapping_schema_missing')


def _title_limit(doctype):
    field=frappe.get_meta(doctype).get_field('title')
    if not field or field.fieldtype!='Data':raise ValueError('title_schema_invalid')
    return int(field.length or 140)


def _long_course_name(plan):
    if len(plan['course_title'])<=140:return None
    return 'avo-'+plan['account']+'-course-'+plan['course_id']


def _sanitize_title(value):
    if '<' not in value and '>' not in value:return value
    from frappe.utils.html_utils import sanitize_html
    return sanitize_html(value)


def _matching(doctype, account, source_id):
    return frappe.get_all(doctype, filters={'custom_avo_account': account, 'custom_avo_id': source_id},
                          fields=['name'], limit_page_length=2)


def _find_image_keys(payload):
    if payload.get('format') == 'ape':
        pending, keys, count = [payload.get('ape')], set(), 0
        while pending:
            node = pending.pop()
            count += 1
            if count > 1000:
                raise ValueError('too_many_blocks')
            if not isinstance(node, dict):
                continue
            if (omit_placeholder_section(node,payload.get('account'),payload.get('course_id'),payload.get('lesson_id')) or
                    omit_placeholder_node(node,payload.get('account'),payload.get('course_id'),payload.get('lesson_id'))):
                continue
            if node.get('name') == 'image':
                key = node.get('id')
                if not isinstance(key, str) or not IMAGE_KEY.fullmatch(key) or key in keys:
                    raise ValueError('invalid_image_key')
                keys.add(key)
            children = node.get('children', [])
            if isinstance(children, list):
                pending.extend(children)
        return keys
    if payload.get('format') != 'preview':
        return set()
    items = payload.get('content', [])
    if not isinstance(items, list):
        return set()
    return {x.get('image_key') for x in items if isinstance(x, dict) and x.get('type') == 'image'}


def _fingerprint(payload, images):
    encoded = json.dumps({'payload': payload, 'image_hashes': {k: v['sha256'] for k, v in sorted(images.items())}},
                         ensure_ascii=True, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf-8')
    return hashlib.sha256(encoded).hexdigest()


def _plan(payload, images):
    keys = _find_image_keys(payload)
    if any(not isinstance(k, str) for k in keys) or keys != set(images):
        raise ValueError('image_keys_mismatch')
    placeholders = {k: '/private/files/' + item['name'] for k, item in images.items()}
    return plan_import(payload, placeholders)


def _snapshot(payload):
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode('utf-8')


def _attached(lesson, filename):
    rows = frappe.get_all('File', filters={'attached_to_doctype': 'Course Lesson',
        'attached_to_name': lesson, 'file_name': filename, 'is_private': 1},
        fields=['name'], limit_page_length=2)
    if len(rows) != 1:
        raise ValueError('existing_lesson_conflict')
    return frappe.get_doc('File', rows[0]['name'])


def _stripped_jpeg(raw):
    from frappe.utils.image import strip_exif_data
    return strip_exif_data(raw, 'image/jpeg')


def _image_matches(image, saved):
    if hashlib.sha256(saved).hexdigest() == image['sha256']:
        return True
    # Frappe may strip JPEG EXIF and apply orientation during File insertion.
    # Compare exact bytes produced by the same transformation, not just pixels.
    return image['name'].endswith('.jpg') and saved == _stripped_jpeg(image['bytes'])


def _lookup(plan, fingerprint, payload, images):
    courses = _matching('LMS Course', plan['account'], plan['course_id'])
    lessons = _matching('Course Lesson', plan['account'], plan['lesson_id'])
    if len(courses) > 1 or len(lessons) > 1:
        raise ValueError('ambiguous_source_id')
    course = frappe.get_doc('LMS Course', courses[0]['name']) if courses else None
    lesson = frappe.get_doc('Course Lesson', lessons[0]['name']) if lessons else None
    if course:
        course.check_permission('write')
        if course.title != _sanitize_title(plan['course_title']):
            raise ValueError('course_title_conflict')
    if lesson:
        if not course or lesson.course != course.name:
            raise ValueError('lesson_course_conflict')
        lesson.check_permission('read')
        if course.published or not lesson.is_draft or lesson.include_in_preview or (lesson.body or '').strip():
            raise ValueError('existing_lesson_conflict')
        if (frappe.db.count('Chapter Reference', {'parent': course.name, 'chapter': lesson.chapter}) != 1 or
                frappe.db.count('Lesson Reference', {'parent': lesson.chapter, 'lesson': lesson.name}) != 1):
            raise ValueError('lesson_outline_conflict')
        saved = _attached(lesson.name, 'avo-source-sha256-' + fingerprint + '.json')
        if saved.get_content(encodings=[]) != _snapshot(payload):
            raise ValueError('existing_lesson_conflict')
        urls = {}
        for key, image in images.items():
            saved_image = _attached(lesson.name, image['name'])
            if not _image_matches(image, saved_image.get_content(encodings=[])):
                raise ValueError('existing_lesson_conflict')
            urls[key] = saved_image.file_url
        expected = plan_import(payload, urls)
        from lms.lms.utils import sanitize_editorjs
        expected_content = sanitize_editorjs(json.dumps({'blocks': expected['blocks'], 'version': '2.29.0'}, ensure_ascii=False))
        try:
            if not expected['ready'] or lesson.title != _sanitize_title(plan['lesson_title']) or json.loads(lesson.content or '{}') != json.loads(expected_content):
                raise ValueError('existing_lesson_conflict')
        except (TypeError, json.JSONDecodeError) as exc:
            raise ValueError('existing_lesson_conflict') from exc
        return course, lesson, 'already_imported'
    if course:
        if course.published:
            raise ValueError('course_published')
        if len(course.chapters or []) != 1:
            raise ValueError('course_chapters_ambiguous')
        chapter = frappe.get_doc('Course Chapter', course.chapters[0].chapter)
        if chapter.course != course.name or chapter.is_scorm_package:
            raise ValueError('course_chapter_invalid')
    return course, None, 'create_lesson' if course else 'create_course_and_lesson'


def _save_private(filename, content, lesson):
    doc = frappe.get_doc({'doctype': 'File', 'file_name': filename, 'is_private': 1,
                          'attached_to_doctype': 'Course Lesson', 'attached_to_name': lesson,
                          'content': content})
    doc.insert()
    if not doc.is_private or not str(doc.file_url).startswith('/private/files/'):
        raise ValueError('private_file_not_confirmed')
    return doc.file_url


def _take_lock():
    name = 'avo-import:' + str(frappe.local.site)
    acquired = frappe.db.sql('SELECT GET_LOCK(%s, %s)', (name, 0))
    if not acquired or acquired[0][0] != 1:
        raise ValueError('import_busy')
    def release():
        frappe.db.sql('SELECT RELEASE_LOCK(%s)', (name,))
    try:
        frappe.db.after_commit.add(release)
        frappe.db.after_rollback.add(release)
    except BaseException:
        release()
        raise


@frappe.whitelist(methods=['POST'])
def import_lesson(payload: dict, images: dict | None = None, dry_run: bool = True):
    """Preview or import one AVO lesson; IDs, private media and source are retained.

    images maps screenshot keys used by preview blocks to base64 PNG/JPEG/WEBP.
    Existing non-identical lessons are never overwritten; dry_run defaults true.
    """
    frappe.only_for('System Manager')
    if isinstance(payload, str):
        payload = json.loads(payload)
    if isinstance(images, str):
        images = json.loads(images)
    if isinstance(dry_run, str):
        if dry_run.lower() not in ('true', 'false', '1', '0'):
            raise ValueError('invalid_dry_run')
        dry_run = dry_run.lower() in ('true', '1')
    if type(dry_run) is not bool or not isinstance(payload, dict):
        raise ValueError('invalid_input')
    if SITE_ACCOUNTS.get(str(frappe.local.site)) != (payload.get('account'), payload.get('source_origin')):
        raise ValueError('site_account_mismatch')
    _schema()
    prepared = _images(images)
    plan = _plan(payload, prepared)
    for kind,doctype in (('course','LMS Course'),('lesson','Course Lesson')):
        if len(_sanitize_title(plan[kind+'_title']))>_title_limit(doctype):
            plan['issues'].append(kind+'_title_exceeds_frappe_limit')
            plan['ready']=False
    # The converter is present before its frontend renderer. Fail closed until
    # the matching renderer has been built, installed and verified on all sites.
    if any(block.get('type') == 'lessonSpacer' for block in plan['blocks']):
        if 'spacer_renderer_not_installed' not in plan['issues']:
            plan['issues'].append('spacer_renderer_not_installed')
        plan['ready'] = False
    result = {'account': plan['account'], 'course_id': plan['course_id'],
              'lesson_id': plan['lesson_id'], 'issues': plan['issues'], 'warnings': plan['warnings'],
              'ready': plan['ready'], 'dry_run': dry_run, 'source_complete': False}
    if not plan['ready']:
        return result
    fingerprint = _fingerprint(payload, prepared)
    if not dry_run:
        _take_lock()
    course, lesson, action = _lookup(plan, fingerprint, payload, prepared)
    result['action'] = action
    if dry_run or lesson:
        if lesson:
            result.update({'course': course.name, 'lesson': lesson.name})
        return result
    from lms.lms.api import create_lesson, upsert_chapter
    if not course:
        if not frappe.has_permission('LMS Course', 'create'):
            raise frappe.PermissionError
        course = frappe.get_doc({'doctype': 'LMS Course', 'title': plan['course_title'],
            'short_introduction': plan['course_title'], 'description': plan['course_title'],
            'published': 0, 'custom_avo_account': plan['account'], 'custom_avo_id': plan['course_id'],
            'instructors': [{'instructor': frappe.session.user}]})
        long_name=_long_course_name(plan)
        if long_name and frappe.db.exists('LMS Course',long_name):
            raise ValueError('reserved_course_name_collision')
        if long_name:course.insert(set_name=long_name)
        else:course.insert()
        chapter = upsert_chapter(title='Уроки курса', course=course.name, is_scorm_package=False)
        chapter_name = chapter.name if hasattr(chapter, 'name') else chapter['name']
    else:
        chapter_name = course.chapters[0].chapter
    lesson_name = create_lesson(chapter=chapter_name)
    lesson = frappe.get_doc('Course Lesson', lesson_name)
    image_urls = {k: _save_private(v['name'], v['bytes'], lesson.name) for k, v in prepared.items()}
    final_plan = plan_import(payload, image_urls)
    if not final_plan['ready']:
        raise ValueError('image_resolution_failed')
    _save_private('avo-source-sha256-' + fingerprint + '.json', _snapshot(payload), lesson.name)
    lesson.update({'title': plan['lesson_title'], 'custom_avo_account': plan['account'],
                   'custom_avo_id': plan['lesson_id'],
                   'is_draft': 1, 'include_in_preview': 0,
                   'content': json.dumps({'blocks': final_plan['blocks'], 'version': '2.29.0'}, ensure_ascii=False),
                   'body': ''})
    lesson.save()
    result.update({'course': course.name, 'lesson': lesson.name, 'action': 'created'})
    return result

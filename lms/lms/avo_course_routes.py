"""Resolve stable AVO course and lesson URLs without changing document names."""
import re

import frappe

from lms.lms.avo_import import SITE_ACCOUNTS


def _id(value):
    return isinstance(value, str) and bool(re.fullmatch(r'[1-9][0-9]{0,19}', value))


def _account():
    row = SITE_ACCOUNTS.get(frappe.local.site)
    return row[0] if row else None


def annotate_course_ids(courses):
    """Add stable IDs to already-authorised course cards in two bounded reads."""
    account = _account()
    names = [c.get('name') for c in courses if c and c.get('name')]
    if not account or not names:
        return courses
    rows = frappe.get_all('LMS Course', filters={'name':['in',names], 'custom_avo_account':account},
                          fields=['name','custom_avo_id'], limit_page_length=0)
    by_name = {row['name']:row.get('custom_avo_id') for row in rows if _id(row.get('custom_avo_id'))}
    if not by_name:
        return courses
    matches = frappe.get_all('LMS Course', filters={'custom_avo_account':account, 'custom_avo_id':['in',list(set(by_name.values()))]},
                             fields=['name','custom_avo_id'], limit_page_length=0)
    counts = {}
    for row in matches:
        ident = row.get('custom_avo_id')
        counts[ident] = counts.get(ident,0) + 1
    for course in courses:
        ident = by_name.get(course.get('name')) if course else None
        if ident and counts.get(ident) == 1:
            course['avo_course_id'] = ident
    return courses


def _permitted(course, lesson=None):
    from lms.lms.utils import can_view_course, guest_access_allowed
    if not guest_access_allowed() or not can_view_course(course):
        return False
    if lesson:
        from lms.lms.permissions import can_access_lesson, get_lesson_gate
        if not can_access_lesson(lesson):
            return False
        locked, _ = get_lesson_gate(course)
        return lesson not in locked
    return True


def _position(course, lesson, expected_chapter):
    chapters = frappe.get_all('Chapter Reference', filters={'parent':course, 'parenttype':'LMS Course'},
                              fields=['chapter','idx'], limit_page_length=0)
    if not chapters:
        return None
    names = [c['chapter'] for c in chapters if c.get('chapter')]
    if not names:
        return None
    refs = frappe.get_all('Lesson Reference', filters={'parent':['in',names], 'parenttype':'Course Chapter', 'lesson':lesson},
                          fields=['parent','idx'], limit_page_length=2)
    positions = [(c.get('idx'), r.get('idx')) for r in refs for c in chapters if c.get('chapter') == r.get('parent')]
    if len(positions) != 1 or any(type(i) is not int or i < 1 for i in positions[0]):
        return None
    chapter_idx, lesson_idx = positions[0]
    if refs[0].get('parent') != expected_chapter or sum(c.get('idx') == chapter_idx for c in chapters) != 1:
        return None
    at_position = frappe.get_all('Lesson Reference', filters={'parent':expected_chapter, 'parenttype':'Course Chapter', 'idx':lesson_idx},
                                 fields=['lesson'], limit_page_length=2)
    if len(at_position) != 1 or at_position[0].get('lesson') != lesson:
        return None
    return positions[0]


@frappe.whitelist(allow_guest=True)
def resolve(course_id, lesson_id=None):
    """Return internal routing keys only when the current user can access them."""
    account = _account()
    if not account or not _id(course_id) or (lesson_id is not None and not _id(lesson_id)):
        return None
    courses = frappe.get_all('LMS Course', filters={'custom_avo_account':account,'custom_avo_id':course_id},
                             fields=['name'], limit_page_length=2)
    if len(courses) != 1:
        return None
    course = courses[0]['name']
    if not _permitted(course):
        return None
    if lesson_id is None:
        return {'course_name':course}
    lessons = frappe.get_all('Course Lesson', filters={'custom_avo_account':account,'custom_avo_id':lesson_id,'course':course},
                             fields=['name','chapter'], limit_page_length=2)
    if len(lessons) != 1 or not _permitted(course, lessons[0]['name']):
        return None
    position = _position(course, lessons[0]['name'], lessons[0].get('chapter'))
    if not position:
        return None
    return {'course_name':course,'lesson_name':lessons[0]['name'],
            'chapter_number':position[0],'lesson_number':position[1]}


@frappe.whitelist(allow_guest=True)
def resolve_course_start(course_id):
    """Resume a permitted course at its saved lesson or first available source ID."""
    target = resolve(course_id)
    if not target:
        return None
    from lms.lms.permissions import can_access_lesson, get_lesson_gate
    from lms.lms.utils import get_membership, get_ordered_lesson_rows
    course = target['course_name']
    names = list(dict.fromkeys(row['name'] for row in get_ordered_lesson_rows(course) if row.get('name')))
    if not names:
        return None
    locked, resume = get_lesson_gate(course)
    membership = get_membership(course)
    preferred = resume or (membership.get('current_lesson') if membership else None)
    candidates = ([preferred] if preferred in names else []) + [name for name in names if name != preferred]
    sources = frappe.get_all('Course Lesson', filters={'name':['in',names],'course':course,'custom_avo_account':_account()},
                             fields=['name','custom_avo_id'], limit_page_length=0)
    ids = {row['name']:row.get('custom_avo_id') for row in sources if _id(row.get('custom_avo_id'))}
    for name in candidates:
        lesson_id = ids.get(name)
        if not lesson_id or name in locked or not can_access_lesson(name):
            continue
        lesson = resolve(course_id, lesson_id)
        if lesson and lesson['course_name'] == course and lesson['lesson_name'] == name:
            return {**lesson, 'course_id':course_id, 'lesson_id':lesson_id}
    return None


@frappe.whitelist(allow_guest=True)
def get_lesson_by_source(course_id, lesson_id):
    """Never return another lesson if its position changed after resolution."""
    target = resolve(course_id, lesson_id)
    if not target:
        return {'locked':1, 'not_found':1}
    from lms.lms.utils import get_lesson
    data = get_lesson(course=target['course_name'], chapter=target['chapter_number'], lesson=target['lesson_number'])
    if not isinstance(data, dict) or data.get('name') != target['lesson_name']:
        return {'locked':1, 'not_found':1}
    return data


@frappe.whitelist()
def resolve_editor(course_id, lesson_id=None):
    """Resolve an edit URL only for staff who can modify this course."""
    target = resolve(course_id, lesson_id)
    if not target:
        return None
    from lms.lms.utils import can_modify_course
    if not can_modify_course(target['course_name']):
        return None
    if lesson_id is not None:
        doc = frappe.get_doc('Course Lesson', target['lesson_name'])
        if not frappe.has_permission('Course Lesson', 'write', doc=doc):
            return None
    return target


@frappe.whitelist()
def resolve_editor_by_lesson(lesson_id):
    """Resolve an AVO editor link containing only its account-scoped lesson ID."""
    account = _account()
    if not account or not _id(lesson_id):
        return None
    lessons = frappe.get_all('Course Lesson', filters={'custom_avo_account':account,'custom_avo_id':lesson_id},
                             fields=['name','course'], limit_page_length=2)
    if len(lessons) != 1 or not lessons[0].get('course'):
        return None
    lesson = lessons[0]
    course = frappe.db.get_value('LMS Course', lesson['course'], ['custom_avo_account','custom_avo_id'], as_dict=True)
    if not course or course.get('custom_avo_account') != account or not _id(course.get('custom_avo_id')):
        return None
    course_id = course['custom_avo_id']
    target = resolve_editor(course_id, lesson_id)
    if not target or target['course_name'] != lesson['course'] or target['lesson_name'] != lesson['name']:
        return None
    return {**target, 'course_id':course_id}


@frappe.whitelist()
def get_editor_by_source(course_id, lesson_id):
    """Fetch editable lesson data directly from its verified document name."""
    target = resolve_editor(course_id, lesson_id)
    if not target:
        frappe.throw('Lesson is unavailable for editing.', frappe.PermissionError)
    fields = ['name','title','include_in_preview','is_draft','publication_audience','lesson_published_at',
              'hide_title_when_locked','body','content','instructor_notes','instructor_content','youtube','quiz_id','chapter',
              'custom_avo_account','custom_avo_id','course']
    lesson = frappe.db.get_value('Course Lesson', target['lesson_name'], fields, as_dict=True)
    if (not lesson or lesson.get('custom_avo_account') != _account() or
        lesson.get('custom_avo_id') != lesson_id or lesson.get('course') != target['course_name']):
        frappe.throw('Lesson is unavailable for editing.', frappe.PermissionError)
    for field in ('custom_avo_account','custom_avo_id','course'):
        lesson.pop(field, None)
    chapter = frappe.db.get_value('Course Chapter', lesson.get('chapter'), ['title','name'], as_dict=True)
    return {'course_title':frappe.db.get_value('LMS Course', target['course_name'], 'title'),
            'chapter':chapter, 'lesson':lesson}


@frappe.whitelist(methods=['POST'])
def save_editor_by_source(course_id, lesson_id, expected_name, values):
    """Recheck source identity and write permission for each autosave."""
    target = resolve_editor(course_id, lesson_id)
    if not target or target['lesson_name'] != expected_name:
        frappe.throw('Lesson identity changed. Please reload.', frappe.PermissionError)
    values = frappe.parse_json(values)
    allowed = {'title','include_in_preview','body','content','instructor_notes','instructor_content'}
    if not isinstance(values,dict) or not values or set(values) - allowed:
        frappe.throw('Invalid lesson fields.', frappe.ValidationError)
    for key, value in values.items():
        if key == 'include_in_preview':
            if type(value) not in (bool,int) or value not in (0,1):
                frappe.throw('Invalid preview setting.', frappe.ValidationError)
        elif (value is not None or key == 'title') and (not isinstance(value,str) or (key == 'title' and len(value) > 512)):
            frappe.throw('Invalid lesson field.', frappe.ValidationError)
    frappe.db.sql('SELECT name FROM `tabCourse Lesson` WHERE name=%s FOR UPDATE', (expected_name,))
    doc = frappe.get_doc('Course Lesson', expected_name)
    if (doc.get('custom_avo_account') != _account() or doc.get('custom_avo_id') != lesson_id or
        doc.get('course') != target['course_name'] or not frappe.has_permission('Course Lesson','write',doc=doc)):
        frappe.throw('Lesson identity changed. Please reload.', frappe.PermissionError)
    doc.update(values)
    doc.save()
    return {'saved':True}


@frappe.whitelist(allow_guest=True)
def canonical(course_name, chapter_number=None, lesson_number=None):
    """Find a canonical route only when the round trip identifies the same row."""
    account = _account()
    if not account or not isinstance(course_name, str) or not course_name or len(course_name) > 255:
        return None
    course = frappe.db.get_value('LMS Course', course_name, ['custom_avo_account','custom_avo_id'], as_dict=True)
    if not course or course.get('custom_avo_account') != account or not _id(course.get('custom_avo_id')):
        return None
    course_id = course['custom_avo_id']
    if chapter_number is None and lesson_number is None:
        target = resolve(course_id)
        return {'course_id':course_id} if target and target['course_name'] == course_name else None
    if not _id(str(chapter_number)) or not _id(str(lesson_number)):
        return None
    chapter = frappe.get_all('Chapter Reference', filters={'parent':course_name,'parenttype':'LMS Course','idx':int(chapter_number)},
                             fields=['chapter'], limit_page_length=2)
    if len(chapter) != 1:
        return None
    refs = frappe.get_all('Lesson Reference', filters={'parent':chapter[0]['chapter'],'parenttype':'Course Chapter','idx':int(lesson_number)},
                          fields=['lesson'], limit_page_length=2)
    if len(refs) != 1:
        return None
    lesson = frappe.db.get_value('Course Lesson', refs[0]['lesson'], ['custom_avo_account','custom_avo_id','course'], as_dict=True)
    if not lesson or lesson.get('course') != course_name or lesson.get('custom_avo_account') != account or not _id(lesson.get('custom_avo_id')):
        return None
    lesson_id = lesson['custom_avo_id']
    target = resolve(course_id,lesson_id)
    if not target or target['course_name'] != course_name or target['chapter_number'] != int(chapter_number) or target['lesson_number'] != int(lesson_number):
        return None
    return {'course_id':course_id,'lesson_id':lesson_id}

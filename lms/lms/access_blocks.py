"""Deny overrides for one learner/course, evaluated before additive grants."""
import hashlib

import frappe
from frappe import _
from frappe.utils import get_datetime, now_datetime

DOCTYPE = 'LMS Access Block'


def rows_block_access(rows, lesson=None, now=None):
    current = get_datetime(now if now is not None else now_datetime())
    for row in rows:
        if not row.get('active') or (row.get('lesson') and row.get('lesson') != lesson):
            continue
        until = row.get('blocked_until')
        if not until:
            return True
        try:
            if current < get_datetime(until):
                return True
        except (TypeError, ValueError):
            # An invalid stored end is not evidence that the ban expired.
            return True
    return False


def _rows(member, course):
    context = getattr(frappe, 'local', None)
    cache = getattr(context, '_lms_access_block_rows', None) if context is not None else None
    if cache is None and context is not None:
        cache = {}
        context._lms_access_block_rows = cache
    key = (member, course)
    if cache is not None and key in cache:
        return cache[key]
    if not frappe.db.table_exists(DOCTYPE):
        return []
    rows = frappe.get_all(DOCTYPE, filters={'member': member, 'course': course, 'active': 1},
        fields=['name', 'lesson', 'active', 'blocked_until', 'owner', 'creation', 'modified_by', 'modified'],
        limit_page_length=0)
    if cache is not None:
        cache[key] = rows
    return rows


def is_blocked(member, course, lesson=None, now=None):
    if not member or member == 'Guest' or not course:
        return False
    return rows_block_access(_rows(member, course), lesson, now)


def _check(course, member, action):
    from lms.lms.staff_authority import require_capability
    require_capability('course_access', action, course=course)
    if (not isinstance(course, str) or not isinstance(member, str)
            or not frappe.db.exists('LMS Course', course)
            or not frappe.db.exists('LMS Enrollment', {'course': course, 'member': member})):
        frappe.throw(_('Course enrollment not found.'), frappe.ValidationError)


@frappe.whitelist()
def get_blocks(course: str, member: str):
    _check(course, member, 'read')
    from lms.lms.staff_authority import has_capability
    actor_visible = has_capability('contacts', 'read') or has_capability('staff', 'read')
    rows = []
    now = now_datetime()
    for source in _rows(member, course):
        row = dict(source)
        row['effective'] = rows_block_access([source], source.get('lesson'), now)
        if not actor_visible:
            row.pop('owner', None)
            row.pop('modified_by', None)
        rows.append(row)
    return {'rows': rows, 'timezone': frappe.utils.get_system_timezone()}


@frappe.whitelist(methods=['POST'])
def set_block(course: str, member: str, blocked, until=None, lesson=None):
    _check(course, member, 'write')
    if type(blocked) not in (int, bool, str) or blocked not in (0, 1, False, True, '0', '1'):
        frappe.throw(_('Choose whether to block access.'), frappe.ValidationError)
    enabled = blocked in (1, True, '1')
    lesson = lesson or None
    if lesson is not None and (not isinstance(lesson, str) or
            frappe.db.get_value('Course Lesson', lesson, 'course') != course):
        frappe.throw(_('The lesson does not belong to this course.'), frappe.ValidationError)
    try:
        if until is not None and not isinstance(until, str):
            raise ValueError()
        end = get_datetime(until) if until else None
        if end and end.tzinfo is not None:
            raise ValueError()
    except (TypeError, ValueError):
        frappe.throw(_('Use a valid block end in the site time zone.'), frappe.ValidationError)
    if enabled and end and end <= now_datetime():
        frappe.throw(_('The block end must be in the future.'), frappe.ValidationError)
    # All writes for a course serialize; deterministic keys avoid duplicate bans.
    frappe.db.get_value('LMS Course', course, 'name', for_update=True)
    name = hashlib.sha256((course + '\0' + member + '\0' + (lesson or '')).encode()).hexdigest()
    if frappe.db.exists(DOCTYPE, name):
        doc = frappe.get_doc(DOCTYPE, name, for_update=True)
        if (doc.course, doc.member, doc.lesson or None) != (course, member, lesson):
            frappe.throw(_('Access block identity mismatch.'), frappe.ValidationError)
    elif enabled:
        doc = frappe.get_doc({'doctype': DOCTYPE, 'name': name, 'course': course, 'member': member, 'lesson': lesson})
    else:
        return {'active': False, 'lesson': lesson, 'blocked_until': None}
    doc.active = int(enabled)
    doc.blocked_until = end if enabled else None
    doc.save(ignore_permissions=True)
    cache = getattr(getattr(frappe, 'local', None), '_lms_access_block_rows', None)
    if cache is not None:
        cache.pop((member, course), None)
    return {'name': doc.name, 'active': enabled, 'lesson': lesson,
            'blocked_until': str(doc.blocked_until) if doc.blocked_until else None}

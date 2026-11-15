"""Bounded course rosters and one-person access views for staff."""
import hashlib
import re

import frappe
from frappe import _
from frappe.utils import get_system_timezone

from lms.lms.avo_contact_card import SITE_ACCOUNTS

PAGE_LENGTHS = (25, 50, 100, 200)
SORTS = {
    'full_name': 'full_name', 'email': 'email', 'phone': 'phone',
    'enrolled_at': 'enrolled_at', 'starts_at': 'starts_at', 'ends_at': 'ends_at',
    'progress': 'progress',
}


def _positive(value, label):
    if type(value) is int and value > 0:
        return value
    if isinstance(value, str) and value.isascii() and value.isdigit() and not value.startswith('0'):
        return int(value)
    frappe.throw(_(label), frappe.ValidationError)


def _pagination(page, page_length):
    page = _positive(page, 'Invalid page.')
    page_length = _positive(page_length, 'Invalid page size.')
    if page_length not in PAGE_LENGTHS or page > 10000000:
        frappe.throw(_('Invalid page size.'), frappe.ValidationError)
    return page, page_length, (page - 1) * page_length


def _check(course, action='read'):
    from lms.lms.staff_authority import require_capability
    if not isinstance(course, str) or not course.strip():
        frappe.throw(_('Course is required.'), frappe.ValidationError)
    require_capability('course_access', action, course=course)
    if not frappe.db.exists('LMS Course', course):
        frappe.throw(_('Not permitted.'), frappe.PermissionError)
    if frappe.get_meta('LMS Course').has_field('custom_avo_account'):
        source = frappe.db.get_value('LMS Course', course, 'custom_avo_account')
        if source and source != SITE_ACCOUNTS.get(frappe.local.site):
            frappe.throw(_('Not permitted.'), frappe.PermissionError)


def _capabilities(course):
    from lms.lms.staff_authority import has_capability
    result = {action: bool(has_capability('course_access', action, course=course))
              for action in ('read', 'write', 'remove')}
    result['contacts_read'] = bool(has_capability('contacts', 'read'))
    return result


def _numeric_id(value):
    return value if isinstance(value, str) and value.isascii() and value.isdigit() and not value.startswith('0') else None


def _enrollment_token(name):
    return hashlib.sha256(name.encode('utf8')).hexdigest()


def _resolve_enrollment(course, enrollment, member=None):
    if enrollment is None:
        return member
    if not isinstance(enrollment, str) or not re.fullmatch('[a-f0-9]{64}', enrollment):
        frappe.throw(_('Invalid enrollment.'), frappe.ValidationError)
    rows = frappe.db.sql('SELECT member FROM `tabLMS Enrollment` WHERE course=%s AND SHA2(name,256)=%s LIMIT 2',
                         (course, enrollment), as_dict=True)
    if len(rows) != 1 or (member and rows[0].member != member):
        frappe.throw(_('Enrollment does not match the selected student and course.'), frappe.ValidationError)
    return rows[0].member


def _roster_sql(account, contacts_read=True):
    """One bounded SQL query; ambiguous contact fallbacks are left blank.

    Course end is the earlier applicable personal/general bound. Several grants
    are shown as several rights, rather than picking an arbitrary winner.
    """
    u_meta, c_meta = frappe.get_meta('User'), frappe.get_meta('Contact')
    identity = all(u_meta.has_field(f) for f in ('custom_avo_account', 'custom_avo_contact_id'))
    account_filter = " AND c.custom_avo_account = %(account)s" if c_meta.has_field('custom_avo_account') and account else ''
    contact_join = ("LEFT JOIN (SELECT c.user, CASE WHEN COUNT(*)=1 THEN MIN(c.email_id) END AS email, "
                    "CASE WHEN COUNT(*)=1 THEN MIN(c.mobile_no) END AS phone FROM `tabContact` c "
                    "WHERE c.user IS NOT NULL AND c.user != ''" + account_filter + " GROUP BY c.user) c ON c.user=u.name")
    route = "CASE WHEN u.custom_avo_account=%(account)s THEN u.custom_avo_contact_id END" if identity and account else 'NULL'
    full_name = 'u.full_name' if contacts_read else "CASE WHEN u.full_name LIKE '%%@%%' THEN CONCAT('Ученик ',LEFT(SHA2(e.name,256),8)) ELSE u.full_name END"
    email = "COALESCE(NULLIF(u.email,''),c.email,'')"
    personal_kind = "CASE WHEN g.personal_end_type='Inherit' THEN p.default_personal_end_type ELSE g.personal_end_type END"
    personal_end = ("CASE WHEN g.personal_end_type='Inherit' THEN CASE p.default_personal_end_type "
                    "WHEN 'At' THEN p.default_personal_end_at WHEN 'After Start' THEN "
                    "DATE_ADD(g.starts_at,INTERVAL p.default_personal_end_days DAY) END "
                    "WHEN g.personal_end_type='At' THEN g.ends_at WHEN g.personal_end_type='After Start' "
                    "THEN DATE_ADD(g.starts_at,INTERVAL g.personal_end_days DAY) END")
    course_kind = "CASE WHEN g.ignore_course_end=1 THEN 'Unlimited' WHEN g.course_end_type='Inherit' THEN p.global_end_type ELSE g.course_end_type END"
    course_end = "CASE WHEN g.course_end_type='Inherit' THEN p.global_end_at ELSE g.course_ends_at END"
    effective = (f"CASE WHEN ({personal_kind}) NOT IN ('Unlimited','At','After Start') OR ({course_kind}) NOT IN ('Unlimited','At') THEN NULL "
                 f"WHEN ({personal_kind})='Unlimited' THEN CASE WHEN ({course_kind})='At' THEN ({course_end}) END "
                 f"WHEN ({course_kind})='Unlimited' THEN ({personal_end}) ELSE LEAST(({personal_end}),({course_end})) END")
    grants = ("LEFT JOIN (SELECT g.member,COUNT(*) AS grant_count,MIN(g.starts_at) AS starts_at, "
              f"CASE WHEN COUNT(*)=1 THEN MIN({effective}) END AS ends_at, "
              "CASE WHEN COUNT(*)=1 THEN MIN(g.status) END AS access_status "
              "FROM `tabLMS Access Grant` g LEFT JOIN `tabLMS Access Policy` p ON p.course=g.course "
              "WHERE g.course=%(course)s AND g.status!='Revoked' GROUP BY g.member) a ON a.member=e.member")
    return (f"SELECT e.name AS enrollment,e.member,{full_name} AS full_name,{email} AS email, "
            f"COALESCE(NULLIF(u.mobile_no,''),c.phone,'') AS phone,{route} AS avo_id, "
            "e.creation AS enrolled_at,COALESCE(a.starts_at,e.creation) AS starts_at,a.ends_at,e.progress, "
            "COALESCE(a.grant_count,0) AS grant_count,a.access_status "
            "FROM `tabLMS Enrollment` e JOIN `tabUser` u ON u.name=e.member "
            f"{contact_join} {grants} WHERE e.course=%(course)s AND e.member_type='Student'")


@frappe.whitelist()
def list_students(course: str, page=1, page_length=50, sort_by='starts_at', sort_dir='desc', search=None):
    _check(course)
    page, page_length, offset = _pagination(page, page_length)
    if not isinstance(sort_by, str) or sort_by not in SORTS or sort_dir not in ('asc', 'desc'):
        frappe.throw(_('Invalid sort order.'), frappe.ValidationError)
    caps = _capabilities(course)
    if sort_by in ('email', 'phone') and not caps['contacts_read']:
        frappe.throw(_('Not permitted.'), frappe.PermissionError)
    if search is not None and (not isinstance(search, str) or len(search) > 140):
        frappe.throw(_('Invalid search query.'), frappe.ValidationError)
    params = {'course': course, 'account': SITE_ACCOUNTS.get(frappe.local.site), 'limit': page_length, 'offset': offset}
    query = 'SELECT * FROM (' + _roster_sql(params['account'], caps['contacts_read']) + ') roster'
    if search and search.strip():
        params['term'] = '%' + search.strip().replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_') + '%'
        query += (' WHERE (full_name LIKE %(term)s OR email LIKE %(term)s OR phone LIKE %(term)s OR avo_id LIKE %(term)s)'
                  if caps['contacts_read'] else ' WHERE full_name LIKE %(term)s')
    total = int(frappe.db.sql('SELECT COUNT(*) FROM (' + query + ') counted', params)[0][0])
    if total and offset >= total:
        page = (total - 1) // page_length + 1
        params['offset'] = (page - 1) * page_length
    elif not total:
        page, params['offset'] = 1, 0
    rows = frappe.db.sql(query + f' ORDER BY {SORTS[sort_by]} {sort_dir.upper()},enrollment ASC LIMIT %(limit)s OFFSET %(offset)s', params, as_dict=True)
    for row in rows:
        row['enrollment'] = _enrollment_token(row['enrollment'])
        row['avo_id'] = _numeric_id(row.get('avo_id'))
        if not caps['contacts_read']:
            row.update(email='', phone='', avo_id=None, member=None)
            if '@' in (row.get('full_name') or ''):
                row['full_name'] = 'Ученик ' + row['enrollment'][:8]
    return {'rows': rows, 'total': total, 'page': page, 'page_length': page_length, 'capabilities': caps}


def _member(course, member, contact=None, enrollment=None):
    member = _resolve_enrollment(course, enrollment, member)
    if contact:
        if not isinstance(contact, str):
            frappe.throw(_('Invalid contact.'), frappe.ValidationError)
        doc = frappe.get_doc('Contact', contact)
        if member and doc.get('user') != member:
            frappe.throw(_('Contact does not match the selected user.'), frappe.ValidationError)
        if doc.get('user'):
            member = doc.user
        else:
            account = SITE_ACCOUNTS.get(frappe.local.site)
            if not account or doc.get('custom_avo_account') != account:
                frappe.throw(_('Not permitted.'), frappe.PermissionError)
            if not frappe.db.exists('DocType', 'AVO Course Access') or not frappe.db.exists('AVO Course Access', {'mapped_contact': contact, 'mapped_course': course}):
                frappe.throw(_('The contact has no archived access to this course.'), frappe.ValidationError)
            return None
    if not isinstance(member, str) or not member or not frappe.db.exists('LMS Enrollment', {'course': course, 'member': member}):
        frappe.throw(_('The student is not enrolled in this course.'), frappe.ValidationError)
    if frappe.get_meta('User').has_field('custom_avo_account'):
        source = frappe.db.get_value('User', member, 'custom_avo_account')
        if source and source != SITE_ACCOUNTS.get(frappe.local.site):
            frappe.throw(_('Not permitted.'), frappe.PermissionError)
    return member


def _provenance(course, member, grant_names):
    """Source capture time is never labelled as the original issue time."""
    if not frappe.db.exists('DocType', 'AVO Course Access'):
        return {}
    rows = frappe.get_all('AVO Course Access', filters={'mapped_course': course, 'mapped_user': member, 'grant': ['in', grant_names]},
                          fields=['grant', 'captured_at', 'sync_status'], limit_page_length=0) if grant_names else []
    return {row.grant: {'kind': 'avo_import', 'label': 'Перенос из АВО', 'snapshot_at': row.captured_at,
                        'actor': None, 'issued_at': None} for row in rows}


def grant_source(grant, archived=None):
    labels = {'Manual': 'Выдан сотрудником', 'Import': 'Импорт', 'Purchase': 'Покупка'}
    kind = grant.get('access_source')
    if kind in labels:
        return {'kind': kind.lower(), 'label': labels[kind], 'actor': grant.get('issued_by'),
                'issued_at': grant.get('issued_at'), 'reference': grant.get('source_reference')}
    return archived or {'kind': 'unknown', 'label': 'Способ выдачи не записан', 'actor': None, 'issued_at': None}


@frappe.whitelist()
def get_member_access(course: str, member=None, contact=None, enrollment=None):
    _check(course)
    member = _member(course, member, contact, enrollment)
    if member is None:
        return {'course': course, 'member': None, 'contact': contact, 'archive_only': True,
                'grants': [], 'capabilities': {'read': True, 'write': False, 'remove': False},
                'notice': 'Связь сохранена в архиве АВО. Учётная запись ученика ещё не связана; изменение доступа недоступно.'}
    fields = ['name', 'member', 'course', 'status', 'starts_at', 'personal_end_type', 'ends_at',
              'personal_end_days', 'ignore_course_end', 'creation', 'owner', 'frozen_at']
    fields.extend(f for f in ('access_source', 'issued_by', 'issued_at', 'source_reference')
                  if frappe.get_meta('LMS Access Grant').has_field(f))
    grants = frappe.get_all('LMS Access Grant', filters={'member': member, 'course': course},
                            fields=fields, order_by='creation desc', limit_page_length=101)
    truncated = len(grants) > 100
    grants = grants[:100]
    provenance = _provenance(course, member, [g.name for g in grants])
    enrollment = frappe.db.get_value('LMS Enrollment', {'course': course, 'member': member},
                                    ['name', 'payment', 'creation', 'owner'], as_dict=True)
    for grant in grants:
        # An untracked legacy grant may have been produced by an import job.
        # We can report persistence metadata, not assert a purchase/manual origin.
        grant['source'] = grant_source(grant, provenance.get(grant.name))
    caps = _capabilities(course)
    if not caps['contacts_read']:
        for grant in grants:
            for field in ('member', 'owner', 'issued_by', 'source_reference'):
                grant.pop(field, None)
            grant['source'] = dict(grant['source'], actor=None, reference=None)
        if enrollment:
            enrollment = dict(enrollment, name=_enrollment_token(enrollment.name))
            enrollment.pop('owner', None)
            enrollment.pop('payment', None)
    policy = frappe.db.get_value('LMS Access Policy', {'course': course}, ['name', 'enabled'], as_dict=True)
    from lms.lms.access_blocks import get_blocks, rows_block_access
    blocks = [dict({key:row.get(key) for key in ('name', 'lesson', 'active', 'blocked_until')},
                   effective=rows_block_access([row], lesson=row.get('lesson')))
              for row in get_blocks(course, member)['rows']]
    return {'course': course, 'member': member if caps['contacts_read'] else None, 'archive_only': False, 'grants': grants,
            'grants_truncated': truncated, 'enrollment': enrollment, 'timezone': get_system_timezone(),
            'release_enabled': frappe.conf.get('individual_access_release_enabled') is True,
            'policy_exists': bool(policy), 'policy_enabled': bool(policy and policy.enabled),
            'capabilities': caps, 'blocks': blocks}


@frappe.whitelist()
def list_member_lessons(course: str, member=None, grant=None, page=1, page_length=50, enrollment=None):
    _check(course)
    member = _member(course, member, enrollment=enrollment)
    page, page_length, offset = _pagination(page, page_length)
    if not isinstance(grant, str) or not frappe.db.exists('LMS Access Grant', {'name': grant, 'course': course, 'member': member}):
        frappe.throw(_('Access grant does not match the student and course.'), frappe.ValidationError)
    total = frappe.db.count('Course Lesson', {'course': course})
    if total and offset >= total:
        page = (total - 1) // page_length + 1
        offset = (page - 1) * page_length
    elif not total:
        page, offset = 1, 0
    rows = frappe.db.sql('''SELECT l.name AS lesson,l.title,r.name AS assignment,r.opening_type,r.opens_at,r.delay_days,
        r.prerequisite_state,r.manual_open FROM `tabCourse Lesson` l
        LEFT JOIN `tabLMS Access Grant Lesson` r ON r.lesson=l.name AND r.parent=%(grant)s
          AND r.parenttype='LMS Access Grant' AND r.parentfield='lessons'
        LEFT JOIN `tabLesson Reference` lr ON lr.lesson=l.name AND lr.parent=l.chapter
        LEFT JOIN `tabChapter Reference` cr ON cr.chapter=l.chapter AND cr.parent=l.course
        WHERE l.course=%(course)s ORDER BY COALESCE(cr.idx,0),COALESCE(lr.idx,0),l.name
        LIMIT %(limit)s OFFSET %(offset)s''', {'grant': grant, 'course': course, 'limit': page_length, 'offset': offset}, as_dict=True)
    return {'rows': rows, 'total': total, 'page': page, 'page_length': page_length}


@frappe.whitelist(methods=['POST'])
def change_lesson_assignment(course: str, grant: str, lesson: str, assigned, member=None, enrollment=None):
    _check(course, 'write')
    member = _member(course, member, enrollment=enrollment)
    if assigned not in (0, 1, '0', '1', False, True):
        frappe.throw(_('Choose whether to assign the lesson.'), frappe.ValidationError)
    document = frappe.get_doc('LMS Access Grant', grant, for_update=True)
    if document.course != course or document.member != member or frappe.db.get_value('Course Lesson', lesson, 'course') != course:
        frappe.throw(_('Access grant does not match the student and course.'), frappe.ValidationError)
    from lms.lms.access_actions import set_grant_assigned_lessons
    lessons = [r.lesson for r in document.lessons]
    enabled = assigned in (1, '1', True)
    if enabled and lesson not in lessons:
        lessons.append(lesson)
    elif not enabled:
        lessons = [name for name in lessons if name != lesson]
    return set_grant_assigned_lessons(grant, lessons)


@frappe.whitelist(methods=['POST'])
def change_member_access(course: str, grant: str, action: str, member=None, values=None, enrollment=None):
    """Bind existing granular mutations to the exact open person/course pair."""
    _check(course, 'remove' if action == 'revoke' else 'write')
    member = _member(course, member, enrollment=enrollment)
    if isinstance(values, str):
        values = frappe.parse_json(values)
    if values is None:
        values = {}
    if not isinstance(values, dict):
        frappe.throw(_('Invalid access settings.'), frappe.ValidationError)
    from lms.lms import access_actions as actions
    methods = {
        'timing': (actions.update_grant_timing, {'starts_at', 'personal_end_type', 'ends_at', 'personal_end_days', 'ignore_course_end'}),
        'freeze': (actions.freeze_grant, set()),
        'resume': (actions.resume_grant, {'extend_personal_end'}),
        'revoke': (actions.revoke_grant, set()),
        'manual_open': (actions.set_grant_lesson_manual_open, {'lesson', 'enabled'}),
        'lesson_rule': (actions.update_grant_lesson_rule, {'lesson', 'rule'}),
    }
    if not isinstance(action, str) or action not in methods or set(values) != methods[action][1]:
        frappe.throw(_('Invalid access action.'), frappe.ValidationError)
    document = frappe.get_doc('LMS Access Grant', grant, for_update=True)
    if document.course != course or document.member != member:
        frappe.throw(_('Access grant does not match the student and course.'), frappe.ValidationError)
    return methods[action][0](grant, **values)


@frappe.whitelist(methods=['POST'])
def create_member_access(course: str, member=None, enrollment=None):
    _check(course, 'write')
    member = _member(course, member, enrollment=enrollment)
    lessons = frappe.get_all('Course Lesson', filters={'course': course}, pluck='name', limit_page_length=5001)
    if len(lessons) > 5000:
        frappe.throw(_('This course requires a separate access migration.'), frappe.ValidationError)
    from lms.lms.access_actions import create_grant_for_enrolled_student
    return create_grant_for_enrolled_student(course, member, lessons=lessons)


@frappe.whitelist(methods=['POST'])
def remove_student(course: str, member=None, enrollment=None):
    _check(course, 'remove')
    expected_enrollment = enrollment
    member = _resolve_enrollment(course, enrollment, member)
    if not isinstance(member, str) or not member:
        frappe.throw(_('Student is required.'), frappe.ValidationError)
    _member(course, member)
    # Same course-first order as enrollment creation, so a concurrent re-enroll
    # cannot slip between closing all grants and removing membership.
    frappe.db.get_value('LMS Course', course, 'name', for_update=True)
    enrollment = frappe.db.get_value('LMS Enrollment', {'course': course, 'member': member}, 'name', for_update=True)
    if not enrollment:
        frappe.throw(_('The student is not enrolled in this course.'), frappe.ValidationError)
    if expected_enrollment and _enrollment_token(enrollment) != expected_enrollment:
        frappe.throw(_('Enrollment changed; reload the student list.'), frappe.ValidationError)
    grants = frappe.get_all('LMS Access Grant', filters={'course': course, 'member': member}, pluck='name', limit_page_length=0)
    archived = []
    if frappe.db.exists('DocType', 'AVO Course Access'):
        names = frappe.get_all('AVO Course Access', filters={'enrollment': enrollment}, pluck='name', limit_page_length=0)
        for name in sorted(names):
            row = frappe.get_doc('AVO Course Access', name, for_update=True)
            if (row.mapped_course != course or row.mapped_user != member
                    or row.account != SITE_ACCOUNTS.get(frappe.local.site)
                    or row.enrollment != enrollment
                    or not row.grant or row.grant not in grants):
                frappe.throw(_('Archived enrollment identity does not match; review the source mapping.'), frappe.ValidationError)
            archived.append(row)
    documents = []
    for name in sorted(grants):
        grant = frappe.get_doc('LMS Access Grant', name, for_update=True)
        if grant.course != course or grant.member != member:
            frappe.throw(_('Access grant identity changed; reload the student list.'), frappe.ValidationError)
        documents.append(grant)
    for grant in documents:
        grant.status, grant.frozen_at = 'Revoked', None
        grant.flags.ignore_permissions = True
        grant.save()
        grant.add_comment('Info', 'Запись ученика в курс удалена сотрудником. Доступ закрыт; результаты обучения сохранены.')
    for row in archived:
        # Source payload/hash/capture date are immutable. Clear only the
        # derived link; retain the revoked grant so a source re-run cannot
        # silently restore access that staff removed.
        frappe.db.set_value('AVO Course Access', row.name, {'enrollment': None,
            'sync_status': 'Needs Review', 'review_reason': 'staff_removed_enrollment'})
        row.add_comment('Info', 'Запись ученика в курс удалена сотрудником; исходный снимок сохранён.')
    frappe.delete_doc('LMS Enrollment', enrollment, ignore_permissions=True)
    return {'removed': True, 'grants_closed': len(grants), 'learning_records_preserved': True}


@frappe.whitelist(methods=['POST'])
def set_member_block(course: str, blocked, member=None, enrollment=None, until=None, lesson=None):
    _check(course, 'write')
    member = _member(course, member, enrollment=enrollment)
    from lms.lms.access_blocks import set_block
    return set_block(course, member, blocked, until=until, lesson=lesson)


@frappe.whitelist()
def get_course_defaults(course: str):
    """Course settings contain defaults/schedules, never a learner roster."""
    _check(course)
    policy = frappe.db.get_value('LMS Access Policy', {'course': course},
        ['name', 'enabled', 'default_personal_end_type', 'default_personal_end_at', 'default_personal_end_days',
         'global_end_type', 'global_end_at', 'completed_retention_type', 'completed_retention_days',
         'visited_retention_type', 'visited_retention_days'], as_dict=True)
    lessons = frappe.get_all('Course Lesson', filters={'course': course}, fields=['name', 'title'],
                             order_by='name asc', limit_page_length=501)
    schedule = frappe.get_all('LMS Access Policy Lesson', filters={'parent': policy.name,
        'parenttype': 'LMS Access Policy', 'parentfield': 'lessons'},
        fields=['lesson', 'opening_type', 'opens_at', 'delay_days', 'not_before_at', 'lesson_ends_at', 'always_open',
                'prerequisite_type', 'prerequisite_lesson', 'prerequisite_assignment'], limit_page_length=0) if policy else []
    return {'release_enabled': frappe.conf.get('individual_access_release_enabled') is True,
            'policy_enabled': bool(policy and policy.enabled), 'policy_exists': bool(policy), 'policy': policy,
            'timezone': get_system_timezone(), 'lessons': lessons[:500], 'lessons_truncated': len(lessons)>500,
            'schedule': schedule, 'grants': [], 'truncated': False, 'capabilities': _capabilities(course)}

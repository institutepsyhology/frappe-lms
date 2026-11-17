"""Learner-facing access explanations. These helpers never grant content access."""
import json

import frappe
from frappe.utils import get_datetime, now_datetime


def _cached(key, read):
    context = getattr(frappe, 'local', None)
    if context is None:
        return read()
    cache = getattr(context, '_access_presentation_cache', None)
    if cache is None:
        cache = {}
        context._access_presentation_cache = cache
    if key not in cache:
        cache[key] = read()
    return cache[key]


def _field(doctype, name, field, default=None):
    if not frappe.get_meta(doctype).has_field(field):
        return default
    return _cached(('field', doctype, name, field), lambda: frappe.db.get_value(doctype, name, field))


def _stamp(value):
    try:
        return get_datetime(value) if value else None
    except (TypeError, ValueError):
        return None


def _date(value):
    dt = _stamp(value)
    return dt.strftime('%d.%m.%Y %H:%M') if dt else ''


def _grants(course, member):
    return _cached(('grants', course, member), lambda: frappe.get_all('LMS Access Grant', filters={'course': course, 'member': member},
        fields=['name', 'status', 'starts_at', 'personal_end_type', 'ends_at', 'personal_end_days',
                'course_end_type', 'course_ends_at', 'ignore_course_end'], limit_page_length=0))


def _bounds(grant, policy):
    from lms.lms.individual_access import resolve_end
    kind, end, days = grant.get('personal_end_type'), grant.get('ends_at'), grant.get('personal_end_days')
    if kind == 'Inherit':
        kind, end, days = (policy.get('default_personal_end_type'), policy.get('default_personal_end_at'),
                           policy.get('default_personal_end_days'))
    kind, end = resolve_end(kind, end, days, grant.get('starts_at'))
    bounds = [(kind, end)]
    if not grant.get('ignore_course_end'):
        course_kind, course_end = grant.get('course_end_type'), grant.get('course_ends_at')
        if course_kind == 'Inherit':
            course_kind, course_end = policy.get('global_end_type'), policy.get('global_end_at')
        bounds.append((course_kind, course_end))
    if any(kind not in ('At', 'Unlimited') or (kind == 'At' and not _stamp(at))
            or (kind == 'Unlimited' and at) for kind, at in bounds):
        return None, False
    dates = [_stamp(at) for kind, at in bounds if kind == 'At']
    return min(dates) if dates else None, True


def course_state(course, member=None):
    """Explain course-level dates, independently of per-lesson release rules."""
    member = member or frappe.session.user
    return dict(_cached(('course_state', course, member), lambda: _course_state(course, member)))


def _course_state(course, member):
    from lms.lms.access_blocks import is_blocked
    from lms.lms.individual_access import policy_applies
    from lms.lms.utils import get_membership
    from lms.lms.permissions import can_author_course
    if can_author_course(course, user=member):
        return {'status': 'Active', 'available': True, 'message': 'Доступ открыт'}
    if is_blocked(member, course):
        return {'status': 'Blocked', 'available': False, 'message': 'Доступ к курсу закрыт администратором.'}
    if not get_membership(course, member):
        return {'status': 'NoAccess', 'available': False, 'message': 'У вас нет доступа к этому курсу.'}
    if not policy_applies(course):
        return {'status': 'Active', 'available': True, 'message': 'Доступ открыт'}
    policy = frappe.db.get_value('LMS Access Policy', {'course': course, 'enabled': 1},
        ['default_personal_end_type', 'default_personal_end_at', 'default_personal_end_days',
         'global_end_type', 'global_end_at'], as_dict=True) or {}
    now = now_datetime()
    starts, ended = [], []
    frozen = False
    for grant in _grants(course, member):
        if grant.get('status') == 'Frozen':
            frozen = True
            continue
        if grant.get('status') not in ('Active', 'Limited'):
            continue
        start = _stamp(grant.get('starts_at'))
        if not start:
            continue
        end, known = _bounds(grant, policy)
        if not known:
            continue
        if end and end <= now:
            ended.append(end)
        elif start > now:
            starts.append(start)
        else:
            return {'status': 'Active', 'available': True, 'message': 'Доступ открыт',
                    'starts_at': str(start), 'ends_at': str(end) if end else None}
    if starts:
        start = min(starts)
        return {'status': 'Scheduled', 'available': False, 'starts_at': str(start),
                'message': 'Курс откроется ' + _date(start) + '.'}
    if frozen:
        return {'status': 'Frozen', 'available': False, 'message': 'Доступ к курсу приостановлен.'}
    if ended:
        end = max(ended)
        return {'status': 'Expired', 'available': False, 'ends_at': str(end),
                'message': 'Срок доступа к курсу закончился ' + _date(end) + '.'}
    return {'status': 'NoAccess', 'available': False, 'message': 'У вас нет действующего доступа к этому курсу.'}


def is_visible(doctype, name):
    # Existing installations exposed titles; preserve that until explicitly disabled.
    return _field(doctype, name, 'show_when_unavailable', 1) != 0


def notice_content(doctype, name):
    """Return only the separately-authored notice, never the protected lesson body."""
    from lms.lms.utils import sanitize_editorjs
    raw = _field(doctype, name, 'access_notice_content')
    try:
        data = json.loads(sanitize_editorjs(raw))
    except (TypeError, ValueError):
        return None
    if not isinstance(data, dict) or not isinstance(data.get('blocks'), list):
        return None
    # Assessments refer to protected resources and can mutate learning progress.
    data['blocks'] = [b for b in data['blocks'] if isinstance(b, dict)
        and b.get('type') not in ('quiz', 'assignment', 'program', 'upload')]
    return json.dumps(data, separators=(',', ':')) if data['blocks'] else None


def course_notice(course):
    return dict(_cached(('course_notice', course, frappe.session.user), lambda: _course_notice(course)))


def visible_course_filters(filters):
    """Apply visibility before pagination/counting so hidden rows leave no gaps."""
    def hidden():
        if not frappe.get_meta('LMS Course').has_field('show_when_unavailable'):
            return []
        names = frappe.get_all('LMS Course', filters={'show_when_unavailable': 0},
            pluck='name', limit_page_length=0)
        return [name for name in names if not course_notice(name)['visible']]
    excluded = _cached(('hidden_courses', frappe.session.user), hidden)
    if not excluded:
        return filters
    from lms.lms.utils import as_filter_conditions
    return as_filter_conditions(filters) + [['name', 'not in', excluded]]


def _course_notice(course):
    state = course_state(course)
    if state['status'] in ('Expired', 'NoAccess'):
        from lms.lms.individual_access import grant_allows_lesson
        grants = [g['name'] for g in _grants(course, frappe.session.user) if g.get('status') in ('Active', 'Limited')]
        lessons = frappe.get_all('LMS Access Grant Lesson', filters={'parent': ('in', grants),
            'parenttype': 'LMS Access Grant', 'parentfield': 'lessons'}, pluck='lesson', limit_page_length=0) if grants else []
        state['retained_access'] = any(grant_allows_lesson(user=frappe.session.user, lesson=lesson, require_retained=True)
            for lesson in lessons)
    state['visible'] = state['available'] or state.get('retained_access') or is_visible('LMS Course', course)
    if not state['available'] and state['visible']:
        state['notice_content'] = notice_content('LMS Course', course)
        if state.get('retained_access'):
            state['message'] += ' Ранее изученные уроки доступны по условиям курса.'
    return state


def _common_rule(course, lesson):
    def read():
        policy = frappe.db.get_value('LMS Access Policy', {'course': course, 'enabled': 1}, 'name')
        rows = frappe.get_all('LMS Access Policy Lesson', filters={'parent': policy,
            'parenttype': 'LMS Access Policy', 'parentfield': 'lessons'},
            fields=['lesson', 'opening_type', 'opens_at', 'delay_days', 'not_before_at'],
            limit_page_length=0) if policy else []
        return {row['lesson']: row for row in rows}
    return _cached(('common_rules', course), read).get(lesson)


def _assigned_rule(grant, lesson):
    def read():
        rows = frappe.get_all('LMS Access Grant Lesson', filters={'parent': grant,
            'parenttype': 'LMS Access Grant', 'parentfield': 'lessons'},
            fields=['lesson', 'opening_type', 'opens_at', 'delay_days', 'manual_open'], limit_page_length=0)
        return {row['lesson']: row for row in rows}
    return _cached(('assigned_rules', grant), read).get(lesson)


def lesson_opening(course, lesson, user):
    """Known scheduled opening, including for an already available lesson."""
    from lms.lms.individual_access import policy_applies, schedule_opening
    if not policy_applies(course):
        return None
    common = _common_rule(course, lesson)
    dates = []
    for grant in _grants(course, user):
        if grant.get('status') not in ('Active', 'Limited') or not _stamp(grant.get('starts_at')):
            continue
        row = _assigned_rule(grant['name'], lesson)
        if not row:
            continue
        opening = schedule_opening(common if row.get('opening_type') == 'Inherit' else row, grant['starts_at'])
        if opening:
            dates.append(max(dt for dt in (_stamp(grant['starts_at']), opening,
                _stamp(common.get('not_before_at')) if common else None) if dt))
    return str(min(dates)) if dates else None


def lesson_notice(course, lesson, user=None):
    """Denied payload for an already-visible lesson; no media/content identifiers."""
    from lms.lms.access_blocks import is_blocked
    from lms.lms.individual_access import policy_applies
    member = user or frappe.session.user
    from lms.lms.permissions import can_author_course, publication_allows_lesson
    publication = frappe.db.get_value('Course Lesson', lesson,
        ['course', 'is_draft', 'publication_audience', 'lesson_published_at'], as_dict=True)
    if not publication or (not can_author_course(course, user=member)
            and not publication_allows_lesson(lesson, publication, member)):
        return {'locked': 1, 'not_found': 1, 'access_denied': 1,
                'access_message': 'Урок не найден или пока не опубликован.'}
    state = course_state(course, member)
    course_denied = not state['available']
    message = state['message'] if course_denied else 'Урок пока недоступен по условиям курса.'
    opens_at = None
    if not course_denied and is_blocked(member, course, lesson):
        message = 'Доступ к уроку закрыт администратором.'
    elif not course_denied and policy_applies(course):
        opening = _stamp(lesson_opening(course, lesson, member))
        if opening and opening > now_datetime():
            opens_at = opening
            message = 'Урок станет доступен ' + _date(opens_at) + '.'
    visible = (is_visible('LMS Course', course) and is_visible('Course Lesson', lesson))
    doctype, name = ('LMS Course', course) if course_denied else ('Course Lesson', lesson)
    show_title = visible and not _field('Course Lesson', lesson, 'hide_title_when_locked', 0)
    return {'locked': 1, 'access_denied': 1, 'name': lesson, 'course': course,
            'title': frappe.db.get_value('Course Lesson', lesson, 'title') if show_title else 'Урок закрыт',
            'course_title': frappe.db.get_value('LMS Course', course, 'title'),
            'access_message': message, 'opens_at': str(opens_at) if opens_at else state.get('starts_at'),
            'notice_content': notice_content(doctype, name) if visible else None}


def lesson_state(course, lesson, user=None):
    """An explanation for a known learner/lesson pair; does not authorize reads."""
    user = user or frappe.session.user
    from lms.lms.permissions import can_access_lesson, can_author_course
    allowed = can_access_lesson(lesson, user=user)
    if allowed and not can_author_course(course, user=user) and frappe.db.get_value('LMS Course', course, 'enforce_lesson_completion'):
        from lms.lms.individual_access import grant_allows_lesson
        if lesson in _sequence_locked(course, user):
            allowed = (grant_allows_lesson(user=user, lesson=lesson, require_schedule_override=True)
                or grant_allows_lesson(user=user, lesson=lesson, require_retained=True))
    if allowed:
        return {'available': True, 'message': 'Доступен к просмотру', 'opens_at': lesson_opening(course, lesson, user)}
    denied = lesson_notice(course, lesson, user=user)
    return {'available': False, 'message': denied['access_message'], 'opens_at': denied.get('opens_at')}


def _sequence_locked(course, user):
    def read():
        from lms.lms.permissions import publication_allows_lesson
        from lms.lms.utils import compute_locked_lessons
        rows = frappe.db.sql('''SELECT l.name,l.course,l.is_draft,l.publication_audience,l.lesson_published_at
            FROM `tabChapter Reference` cr JOIN `tabCourse Chapter` c ON c.name=cr.chapter
            JOIN `tabLesson Reference` lr ON lr.parent=c.name JOIN `tabCourse Lesson` l ON l.name=lr.lesson
            WHERE cr.parent=%s ORDER BY cr.idx,lr.idx''', (course,), as_dict=True)
        names = [r.name for r in rows if publication_allows_lesson(r.name, r, user)]
        completed = set(frappe.get_all('LMS Course Progress', filters={'course': course, 'member': user,
            'status': 'Complete'}, pluck='lesson', limit_page_length=0))
        return compute_locked_lessons(names, completed)
    return _cached(('sequence_locked', course, user), read)


@frappe.whitelist()
def get_visibility_settings(course, lesson=None):
    from lms.lms.course_people import _check
    _check(course, 'read')
    if lesson and frappe.db.get_value('Course Lesson', lesson, 'course') != course:
        frappe.throw('Урок не относится к этому курсу.', frappe.ValidationError)
    doctype, name = ('Course Lesson', lesson) if lesson else ('LMS Course', course)
    return {'show_when_unavailable': is_visible(doctype, name),
            'access_notice_content': _field(doctype, name, 'access_notice_content')}


@frappe.whitelist(methods=['POST'])
def save_visibility_settings(course, show_when_unavailable, access_notice_content=None, lesson=None):
    from lms.lms.course_people import _check
    _check(course, 'write')
    if lesson and frappe.db.get_value('Course Lesson', lesson, 'course') != course:
        frappe.throw('Урок не относится к этому курсу.', frappe.ValidationError)
    if type(show_when_unavailable) not in (bool, int) or show_when_unavailable not in (0, 1):
        frappe.throw('Выберите, показывать ли закрытый материал.', frappe.ValidationError)
    from lms.lms.utils import sanitize_editorjs
    doctype, name = ('Course Lesson', lesson) if lesson else ('LMS Course', course)
    if access_notice_content:
        try:
            data = json.loads(access_notice_content)
            if not isinstance(data, dict) or not isinstance(data.get('blocks'), list):
                raise ValueError()
        except (TypeError, ValueError):
            frappe.throw('Не удалось прочитать сообщение. Сохраните его повторно.', frappe.ValidationError)
    frappe.db.set_value(doctype, name, {'show_when_unavailable': int(show_when_unavailable),
        'access_notice_content': sanitize_editorjs(access_notice_content) if access_notice_content else None})
    return {'saved': True}

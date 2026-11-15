"""One staff contact workspace for User and Contact records.

Contact data and course access have independent capabilities. Credential values
are never part of these responses; their existing audited methods stay separate.
"""
import json

import frappe
from frappe import _

from lms.lms import avo_contact_card as legacy
from lms.lms.staff_authority import has_capability, require_capability

PAGE_SIZES = (25, 50, 100, 200)
SORT_FIELDS = frozenset({'title', 'starts_at', 'ends_at', 'enrolled_at', 'source_type'})
PEOPLE_SORT_FIELDS = frozenset({'full_name', 'email', 'mobile_no', 'source_id'})


def _manager():
    return frappe.session.user == 'Administrator' or 'System Manager' in frappe.get_roles()


def _scoped(doc):
    account = doc.get('custom_avo_account')
    expected = legacy.SITE_ACCOUNTS.get(frappe.local.site)
    if account and account != expected:
        frappe.throw(_('This contact belongs to another source account.'), frappe.PermissionError)
    return doc


def _identity(kind, name):
    doc = _scoped(legacy._document(kind, name))
    contact = doc.name if doc.doctype == 'Contact' else None
    if doc.doctype == 'Contact' and doc.get('user'):
        linked = _scoped(legacy._document('User', doc.user))
        if (doc.get('custom_avo_contact_id') and linked.get('custom_avo_contact_id') and
                doc.custom_avo_contact_id != linked.custom_avo_contact_id):
            frappe.throw(_('Contact identity is ambiguous.'), frappe.ValidationError)
        doc = linked
    return doc, contact


def _staff_target(doc):
    if doc.doctype != 'User': return False
    from lms.lms.support_credentials import PRIVILEGED_ROLES
    from lms.lms.credential_profiles import can_manage_credentials
    return bool(doc.user_type == 'System User' or PRIVILEGED_ROLES.intersection(frappe.get_roles(doc.name))
                or can_manage_credentials(doc.name))


def _editable_target(doc):
    return bool(has_capability('contacts', 'write') and (_manager() or not _staff_target(doc)))


def _card(doc, contact=None):
    result = legacy._present(doc)
    credential_target = doc.doctype == 'User' and (_manager() or not _staff_target(doc))
    result.update(user_name=doc.name if doc.doctype == 'User' else None, contact_name=contact,
                  capabilities={'read': True, 'write': _editable_target(doc),
                      **{'credential_' + action: credential_target and bool(has_capability('credentials', action))
                         for action in ('read', 'write', 'send')}})
    return result


@frappe.whitelist()
def get_capabilities():
    return {action: bool(has_capability('contacts', action)) for action in ('read', 'write', 'create')}


@frappe.whitelist()
def resolve_source_id(source_id):
    require_capability('contacts', 'read')
    if not isinstance(source_id, str) or not source_id.isascii() or not source_id.isdigit() or source_id.startswith('0') or len(source_id) > 20:
        frappe.throw(_('Invalid contact ID.'), frappe.ValidationError)
    account = legacy.SITE_ACCOUNTS.get(frappe.local.site)
    if not account: frappe.throw(_('Unknown AVO account.'), frappe.ValidationError)
    filters = {'custom_avo_account': account, 'custom_avo_contact_id': source_id}
    users = frappe.get_all('User', filters=filters, fields=['name'], limit_page_length=2)
    contacts = frappe.get_all('Contact', filters=filters, fields=['name', 'user'], limit_page_length=2)
    if len(users) == 1 and len(contacts) <= 1 and all(row.user == users[0].name for row in contacts):
        return {'kind': 'User', 'name': users[0].name}
    if not users and len(contacts) == 1:
        return {'kind': 'Contact', 'name': contacts[0].name}
    frappe.throw(_('Contact ID not found or is ambiguous.'), frappe.ValidationError)


@frappe.whitelist()
def list_people(page=1, page_size=50, search=None, sort='full_name', direction='asc'):
    require_capability('contacts', 'read')
    page, page_size = _page_options(page, page_size, 'title', direction)
    if sort not in PEOPLE_SORT_FIELDS or (search is not None and (not isinstance(search, str) or len(search) > 140)):
        frappe.throw(_('Invalid search or sorting.'), frappe.ValidationError)
    account = legacy.SITE_ACCOUNTS.get(frappe.local.site)
    if not account: frappe.throw(_('Unknown AVO account.'), frappe.ValidationError)
    # Both branches project only basic contact fields. A linked Contact is
    # represented by its User once; no account or employee roles are returned.
    union = '''SELECT 'User' AS kind,u.name,u.full_name,u.email,u.mobile_no,u.custom_avo_contact_id AS source_id
        FROM `tabUser` u WHERE u.name NOT IN ('Administrator','Guest')
        AND (u.custom_avo_account=%s OR COALESCE(u.custom_avo_account,'')='')
        UNION ALL
        SELECT 'Contact' AS kind,c.name,c.full_name,c.email_id AS email,c.mobile_no,c.custom_avo_contact_id AS source_id
        FROM `tabContact` c WHERE (c.custom_avo_account=%s OR COALESCE(c.custom_avo_account,'')='')
        AND NOT EXISTS (SELECT 1 FROM `tabUser` linked WHERE linked.name=c.user)'''
    params = [account, account]
    where = ''
    if search and search.strip():
        pattern = '%' + search.strip().replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_') + '%'
        where = ' WHERE (p.full_name LIKE %s OR p.email LIKE %s OR p.mobile_no LIKE %s OR p.source_id LIKE %s)'
        params.extend([pattern] * 4)
    total = frappe.db.sql('SELECT COUNT(*) FROM (' + union + ') p' + where, params)[0][0]
    order = 'CAST(NULLIF(p.source_id,\'\') AS UNSIGNED)' if sort == 'source_id' else 'p.' + sort
    sql = ('SELECT p.* FROM (' + union + ') p' + where + ' ORDER BY ' + order + ' ' + direction.upper()
           + ',p.kind ASC,p.name ASC LIMIT %s OFFSET %s')
    rows = frappe.db.sql(sql, [*params, page_size, (page - 1) * page_size], as_dict=True)
    return {'rows': rows, 'total': total, 'page': page, 'page_size': page_size,
            'has_next_page': page * page_size < total, 'can_create': bool(has_capability('contacts', 'create'))}


@frappe.whitelist(methods=['POST'])
def create_contact(values):
    """Create only a contact: no login, enrollment or employee role is added."""
    require_capability('contacts', 'create')
    if isinstance(values, str): values = frappe.parse_json(values)
    allowed = set(legacy.EDITABLE) | {'email'}
    if not isinstance(values, dict) or set(values) - allowed:
        frappe.throw(_('Invalid contact fields.'), frappe.ValidationError)
    if any(not isinstance(value, str) or len(value) > 140 for value in values.values()):
        frappe.throw(_('Invalid contact field.'), frappe.ValidationError)
    values = {field: value.strip() for field, value in values.items()}
    if not any(values.get(field) for field in allowed):
        frappe.throw(_('Provide a name, email, phone or social account.'), frappe.ValidationError)
    email, phone = values.pop('email', ''), values.pop('mobile_no', '')
    if email:
        from frappe.utils import validate_email_address
        if not validate_email_address(email, throw=False):
            frappe.throw(_('Enter a valid email address.'), frappe.ValidationError)
    doc = frappe.get_doc({'doctype': 'Contact', **values})
    if email: doc.append('email_ids', {'email_id': email, 'is_primary': 1})
    if phone: doc.append('phone_nos', {'phone': phone, 'is_primary_mobile_no': 1})
    # Social-only contacts are legitimate; do not fabricate a person's name or
    # an email just to satisfy the standard Contact mandatory-name field.
    doc.insert(set_name='contact-' + frappe.generate_hash(length=12), ignore_permissions=True,
               ignore_mandatory=not bool(doc.get('first_name')))
    return {'kind': 'Contact', 'name': doc.name}


@frappe.whitelist()
def get_card(kind, name):
    require_capability('contacts', 'read')
    doc, contact = _identity(kind, name)
    return _card(doc, contact)


@frappe.whitelist(methods=['POST'])
def save_card(kind, name, values):
    require_capability('contacts', 'write')
    doc, contact = _identity(kind, name)
    if not _editable_target(doc):
        frappe.throw(_('Only a system manager can edit a staff account.'), frappe.PermissionError)
    if isinstance(values, str):
        values = frappe.parse_json(values)
    allowed = set(legacy.EDITABLE) | {'custom_no_marketing_email'} | ({'email'} if doc.doctype == 'Contact' else set())
    if not isinstance(values, dict) or set(values) - allowed:
        frappe.throw(_('Invalid contact fields.'), frappe.ValidationError)
    meta = frappe.get_meta(doc.doctype)
    for field, value in values.items():
        if field == 'custom_no_marketing_email':
            if type(value) not in (bool, int) or value not in (0, 1):
                frappe.throw(_('Invalid marketing preference.'), frappe.ValidationError)
            doc.set(field, int(value))
            continue
        if not isinstance(value, str) or len(value) > 140 or (field != 'email' and not meta.has_field(field)):
            frappe.throw(_('Invalid contact field.'), frappe.ValidationError)
        value = value.strip()
        if doc.doctype == 'Contact' and field in ('email', 'mobile_no'):
            if field == 'email':
                from frappe.utils import validate_email_address
                if value and not validate_email_address(value, throw=False):
                    frappe.throw(_('Enter a valid email address.'), frappe.ValidationError)
                table, primary, key = 'email_ids', 'is_primary', 'email_id'
            else:
                table, primary, key = 'phone_nos', 'is_primary_mobile_no', 'phone'
            selected = next((row for row in doc.get(table) or [] if row.get(primary)), None)
            if selected:
                if value: selected.set(key, value)
                else: doc.remove(selected)
            elif value:
                doc.append(table, {key: value, primary: 1})
        else:
            doc.set(field, value)
    save_options = {'ignore_permissions': True}
    if doc.doctype == 'Contact' and not doc.get('first_name'):
        identity = any(doc.get(field) for field in ('middle_name', 'last_name', *legacy.SOCIAL_FIELDS))
        identity = identity or any(row.get('email_id') for row in doc.get('email_ids') or [])
        identity = identity or any(row.get('phone') for row in doc.get('phone_nos') or [])
        if not identity:
            frappe.throw(_('Provide a name, email, phone or social account.'), frappe.ValidationError)
        doc.flags.ignore_mandatory = True
    doc.save(**save_options)
    if doc.get('custom_no_marketing_email') and doc.get('custom_avo_account') and doc.get('custom_avo_contact_id'):
        from lms.lms.avo_marketing import protect_existing_groups
        protect_existing_groups(doc.custom_avo_account, [doc.custom_avo_contact_id])
    return _card(doc, contact)


def _page_options(page, page_size, sort, direction):
    if any(type(value) is not int and not (isinstance(value, str) and value.isascii() and value.isdigit())
           for value in (page, page_size)):
        frappe.throw(_('Invalid page.'), frappe.ValidationError)
    try:
        page = int(page)
        page_size = int(page_size)
    except (TypeError, ValueError):
        frappe.throw(_('Invalid page.'), frappe.ValidationError)
    if page < 1 or page > 10000000 or page_size not in PAGE_SIZES or sort not in SORT_FIELDS or direction not in ('asc', 'desc'):
        frappe.throw(_('Invalid page or sorting.'), frappe.ValidationError)
    return page, page_size


def _source_rows(doc):
    account, source_id = doc.get('custom_avo_account'), doc.get('custom_avo_contact_id')
    if not account or not source_id or not frappe.db.exists('DocType', 'AVO Course Access'):
        return []
    return frappe.get_all('AVO Course Access', filters={'account': account, 'source_contact_id': source_id},
        fields=['source_access_id', 'source_course_id', 'mapped_course', 'grant', 'sync_status',
                'source_payload', 'captured_at', 'creation', 'owner'], limit_page_length=0)


def _source_dates(source):
    try:
        record = json.loads(source.get('source_payload') or '{}')
        access = record.get('access') or {}
        if not isinstance(access, dict): return None, None
        return access.get('opens_at'), access.get('effective_closes_at') or access.get('closes_at')
    except (ValueError, TypeError, AttributeError):
        return None, None


def _end(kind, value, days, start):
    from lms.lms.individual_access import resolve_end
    return resolve_end(kind, value, days, start)


def _grant_dates(grant, policy):
    start = grant.get('starts_at')
    kind, value, days = grant.get('personal_end_type'), grant.get('ends_at'), grant.get('personal_end_days') or 0
    if kind == 'Inherit':
        kind, value, days = policy.get('default_personal_end_type'), policy.get('default_personal_end_at'), policy.get('default_personal_end_days') or 0
    kind, value = _end(kind, value, days, start)
    ends, unknown = ([str(value)] if kind == 'At' and value else []), kind not in ('At', 'Unlimited')
    if not grant.get('ignore_course_end'):
        course_kind, course_end = grant.get('course_end_type'), grant.get('course_ends_at')
        if course_kind == 'Inherit': course_kind, course_end = policy.get('global_end_type'), policy.get('global_end_at')
        if course_kind == 'At' and course_end: ends.append(str(course_end))
        elif course_kind != 'Unlimited': unknown = True
    return start, min(ends) if ends else None, unknown


def _course_rows(doc):
    from lms.lms.course_people import grant_source
    member = doc.name if doc.doctype == 'User' else None
    enrollments = frappe.get_all('LMS Enrollment', filters={'member': member},
        fields=['name', 'course', 'creation', 'owner', 'progress'], limit_page_length=0) if member else []
    grant_fields = ['name', 'course', 'status', 'starts_at', 'personal_end_type', 'ends_at', 'personal_end_days',
                    'course_end_type', 'course_ends_at', 'ignore_course_end', 'creation', 'owner']
    grant_fields.extend(field for field in ('access_source', 'issued_by', 'issued_at', 'source_reference')
                        if frappe.get_meta('LMS Access Grant').has_field(field))
    grants = frappe.get_all('LMS Access Grant', filters={'member': member},
                            fields=grant_fields, limit_page_length=0) if member else []
    sources = _source_rows(doc)
    grouped = {}
    for kind, rows in (('enrollments', enrollments), ('grants', grants), ('sources', sources)):
        for row in rows:
            course = row.get('course') or row.get('mapped_course')
            key = course or 'avo:' + str(row.get('source_course_id'))
            group = grouped.setdefault(key, {'course': course, 'enrollments': [], 'grants': [], 'sources': []})
            group[kind].append(row)
    ids = [value['course'] for value in grouped.values() if value['course']]
    course_fields = ['name', 'title']
    if frappe.get_meta('LMS Course').has_field('custom_avo_account'): course_fields.append('custom_avo_account')
    courses = {row.name: row for row in frappe.get_all('LMS Course', filters={'name': ['in', ids]},
        fields=course_fields, limit_page_length=0)} if ids else {}
    policies = {row.course: row for row in frappe.get_all('LMS Access Policy', filters={'course': ['in', ids]},
        fields=['course', 'default_personal_end_type', 'default_personal_end_at', 'default_personal_end_days',
                'global_end_type', 'global_end_at'], limit_page_length=0)} if ids else {}
    result = []
    for key, group in grouped.items():
        course = group['course']
        metadata = courses.get(course) or {}
        if metadata.get('custom_avo_account') and metadata['custom_avo_account'] != legacy.SITE_ACCOUNTS.get(frappe.local.site):
            continue
        if not has_capability('course_access', 'read', course=course): continue
        ordered = sorted(group['sources'], key=lambda x: int(x.get('source_access_id') or 0)
                         if str(x.get('source_access_id') or '').isascii() and str(x.get('source_access_id') or '').isdigit() else -1,
                         reverse=True)
        source = ordered[0] if ordered else None
        ordered_grants = sorted(group['grants'], key=lambda x: (str(x.get('creation') or ''), x['name']), reverse=True)
        selected = next((grant for grant in ordered_grants if source and source.get('grant') == grant['name']), None)
        selected = selected or (ordered_grants[0] if ordered_grants else None)
        enrollment = min(group['enrollments'], key=lambda x: (str(x.get('creation') or ''), x['name']), default=None)
        if selected:
            start, end, unknown = _grant_dates(selected, policies.get(course) or {})
        else:
            start, end = _source_dates(source) if source else (None, None)
            unknown = not source
        archived = {'kind': 'avo_import', 'label': 'Перенос из АВО', 'actor': None, 'issued_at': None} if source else None
        origin = grant_source(selected or {}, archived)
        result.append({'course': course, 'source_course_id': source.get('source_course_id') if source else None,
            'title': (courses.get(course) or {}).get('title') or ('Курс АВО № ' + str(source.get('source_course_id')) if source else course),
            'starts_at': str(start) if start else None, 'ends_at': str(end) if end else None,
            'end_unknown': unknown, 'enrolled_at': str(enrollment.creation) if enrollment else None,
            'progress': enrollment.get('progress') if enrollment else None,
            'status': selected.get('status') if selected else source.get('sync_status') if source else 'Unknown',
            'grant_count': len(ordered_grants), 'archive_only': not member or not selected,
            'source_type': origin['kind'], 'source_label': origin['label'],
            'source_event_at': str(origin['issued_at']) if origin.get('issued_at') else None,
            'source_actor': origin.get('actor'), 'source_reference': origin.get('reference'),
            'imported_at': str(source.creation) if source else None, 'imported_by': source.get('owner') if source else None,
            'source_captured_at': str(source.captured_at) if source and source.get('captured_at') else None,
            'can_edit': bool(member and course and has_capability('course_access', 'write', course=course)),
            'grants': [{key: grant.get(key) for key in ('name', 'status', 'starts_at', 'ends_at')} for grant in ordered_grants],
            '_key': key})
    return result


@frappe.whitelist()
def list_person_courses(kind, name, page=1, page_size=50, sort='title', direction='asc'):
    require_capability('contacts', 'read')
    page, page_size = _page_options(page, page_size, sort, direction)
    doc, _ = _identity(kind, name)
    rows = _course_rows(doc)
    # A person's courses are fetched in batches; only this selected page and
    # allowed fields are returned. Never load all students of any course here.
    rows.sort(key=lambda row: row['_key'])
    rows.sort(key=lambda row: (row.get(sort) is None, str(row.get(sort) or '').casefold()), reverse=direction == 'desc')
    total = len(rows)
    start = (page - 1) * page_size
    selected = [{key: value for key, value in row.items() if key != '_key'} for row in rows[start:start + page_size]]
    return {'rows': selected, 'total': total, 'page': page, 'page_size': page_size,
            'has_next_page': start + page_size < total}

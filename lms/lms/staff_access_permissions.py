"""Deny-only native document guards for explicitly assigned staff positions."""
import frappe


def contact_document_permission(doc, ptype='read', user=None, **kwargs):
    from lms.lms.staff_policy import assigned_capability
    from lms.lms.staff_authority import user_delete_permission
    user = user or frappe.session.user
    if doc.doctype == 'User':
        denied = user_delete_permission(doc, user=user, ptype=ptype)
        if denied is False:
            return False
    if user == 'Administrator':
        return None
    own = doc.name == user if doc.doctype == 'User' else doc.get('user') == user
    if own and ptype in ('read', 'select', 'write'):
        return None
    action = {'read':'read', 'select':'read', 'report':'read', 'print':'read',
              'create':'create', 'write':'write', 'delete':'delete'}.get(ptype, 'read')
    if assigned_capability('contacts', action, user=user) is False:
        return False
    return None


def _contact_query_conditions(doctype, user=None):
    from lms.lms.staff_policy import assigned_capability
    user = user or frappe.session.user
    if user == 'Administrator' or assigned_capability('contacts', 'read', user=user) is not False:
        return ''
    field = 'name' if doctype == 'User' else 'user'
    return '`tab' + doctype + '`.' + field + '=' + frappe.db.escape(user)


def user_query_conditions(user=None):
    return _contact_query_conditions('User', user)


def contact_query_conditions(user=None):
    return _contact_query_conditions('Contact', user)


def check_membership_row(doc, method=None):
    """Close direct child-document API paths as well as parent User saves."""
    if frappe.session.user == 'Administrator':
        return
    from lms.lms.staff_authority import require_role_change
    require_role_change(doc.get('parent'), doc.get('role'))


def role_definition_permission(doc, ptype='read', user=None, **kwargs):
    user = user or frappe.session.user
    if user != 'Administrator' and ptype not in ('read', 'select', 'print'):
        return False
    return None


def has_permission(doc, ptype='read', user=None, **kwargs):
    from lms.lms.staff_policy import assigned_capability
    user = user or frappe.session.user
    if user == 'Administrator':
        return None
    action = {'read':'read', 'select':'read', 'report':'read', 'print':'read',
              'create':'create', 'write':'write', 'delete':'remove'}.get(ptype)
    if action is None:
        action = 'write'
    previous = None if doc.is_new() else frappe.db.get_value(doc.doctype, doc.name,
        ['course', 'member'] if doc.doctype == 'LMS Enrollment' else ['course'], as_dict=True)
    course = previous.get('course') if previous else doc.get('course')
    # Enrollment progress remains the learner's own surface. Changing the
    # membership identity is a staff operation, not a profile/progress edit.
    if doc.doctype == 'LMS Enrollment' and doc.get('member') == user:
        own = not previous or (previous.member == user and previous.course == doc.get('course'))
        if own and ptype in ('read', 'select', 'write', 'create'):
            return None
    explicit = assigned_capability('course_access', action, course=course, user=user)
    if explicit is None:
        return None
    if not explicit:
        return False
    if previous and previous.course != doc.get('course'):
        if not assigned_capability('course_access', action, course=doc.get('course'), user=user):
            return False
    return None


def enrollment_query_conditions(user=None):
    from lms.lms.staff_policy import assigned_position
    user = user or frappe.session.user
    if user == 'Administrator':
        return ''
    position = assigned_position(user)
    if position is None:
        return ''
    member = frappe.db.escape(user)
    own = '`tabLMS Enrollment`.member=' + member
    if not position['active'] or ('course_access','read') not in position['permissions']:
        return own
    if position['scope'] == 'All':
        return ''
    return '(' + own + ''' OR `tabLMS Enrollment`.course IN (
      SELECT name FROM `tabLMS Course` WHERE owner=''' + member + ''' UNION
      SELECT parent FROM `tabCourse Instructor` WHERE parenttype='LMS Course' AND instructor=''' + member + '))'

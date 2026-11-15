"""Explicit staff positions bound app capabilities; native roles are not grants."""
import frappe
from frappe import _
from contextlib import contextmanager
from dataclasses import dataclass


RESOURCES = {
    'contacts': ('read', 'create', 'write', 'delete'),
    'course_access': ('read', 'create', 'write', 'remove'),
    'staff': ('read', 'create', 'write', 'delete'),
    'positions': ('read', 'create', 'write', 'delete'),
    'credentials': ('read', 'write', 'send'),
}
NATIVE_ROLES = frozenset({'Moderator', 'Course Creator', 'Batch Evaluator', 'LMS Student'})
LEGACY_MODERATOR = frozenset(
    [('contacts', action) for action in ('read', 'create', 'write')]
    + [('course_access', action) for action in ('read', 'create', 'write', 'remove')]
)


@dataclass(frozen=True)
class _UserWrite:
    actor: str
    target: str
    roles: frozenset
    enabled: int


@contextmanager
def _controlled_user_write(target, roles, enabled):
    """Server-only scope used after the assignment API's bounded checks."""
    previous = getattr(frappe.flags, '_lms_staff_user_write', None)
    frappe.flags._lms_staff_user_write = _UserWrite(frappe.session.user, target, frozenset(roles), int(enabled))
    try:
        yield
    finally:
        frappe.flags._lms_staff_user_write = previous


def is_controlled_user_change(doc):
    scope = getattr(getattr(frappe, 'flags', None), '_lms_staff_user_write', None)
    if not isinstance(scope, _UserWrite) or scope.actor != frappe.session.user or scope.target != doc.name:
        return False
    if scope.actor != 'Administrator' and doc.name == scope.actor:
        return False
    roles = frozenset(r.get('role') for r in (doc.get('roles') or []))
    if (roles != scope.roles or not roles <= NATIVE_ROLES or doc.get('role_profiles')
            or doc.get('role_profile_name') or doc.get('enabled') != scope.enabled
            or doc.get('user_type') not in ('Website User', 'System User')):
        return False
    before = doc.get_doc_before_save()
    if before is not None:
        for field in ('module_profile', 'restrict_ip', 'bypass_restrict_ip_check_if_2fa_enabled', 'login_after', 'login_before'):
            if (doc.get(field) or None) != (before.get(field) or None):
                return False
    return True


def permission_pairs(rows):
    """Reject unknown or duplicate matrix cells, including forged API input."""
    if not isinstance(rows, (list, tuple)):
        frappe.throw(_('Invalid permission matrix.'), frappe.ValidationError)
    pairs = set()
    for row in rows:
        if not hasattr(row, 'get'):
            frappe.throw(_('Invalid permission matrix.'), frappe.ValidationError)
        pair = (row.get('resource'), row.get('action'))
        if (not all(isinstance(value,str) for value in pair) or pair[0] not in RESOURCES
                or pair[1] not in RESOURCES[pair[0]] or pair in pairs):
            frappe.throw(_('Invalid permission matrix.'), frappe.ValidationError)
        pairs.add(pair)
    if any(resource != 'credentials' and action != 'read' and (resource, 'read') not in pairs
           for resource, action in pairs):
        frappe.throw(_('Read access is required for changes in this section.'), frappe.ValidationError)
    return frozenset(pairs)


def _cache():
    local = getattr(frappe, 'local', None)
    if local is None:
        return {}
    result = getattr(local, '_lms_staff_policy_cache', None)
    if result is None:
        result = {}
        local._lms_staff_policy_cache = result
    return result


def clear_policy_cache():
    local = getattr(frappe, 'local', None)
    if local is not None:
        local._lms_staff_policy_cache = {}


def assigned_position(user=None):
    """None means no policy; an inactive assignment still overrides fallback."""
    user = user or frappe.session.user
    cache = _cache()
    key = ('position', user)
    if key not in cache:
        cache[key] = _load_position(user)
    return cache[key]


def _load_position(user):
    if not frappe.db.table_exists('LMS Staff Assignment'):
        return None
    rows = frappe.get_all('LMS Staff Assignment', filters={'user': user},
                          fields=['name', 'position', 'active'], limit_page_length=2)
    if not rows:
        return None
    if len(rows) != 1:
        frappe.throw(_('Staff assignment is ambiguous.'), frappe.PermissionError)
    row = rows[0]
    if not row.active or not row.position:
        return {'assignment': row.name, 'name': row.position, 'active': False,
                'permissions': frozenset(), 'roles': frozenset(), 'scope': 'Owned'}
    position = frappe.get_doc('LMS Staff Position', row.position)
    roles = frozenset(r.get('role') for r in (position.get('native_roles') or []))
    if not roles <= NATIVE_ROLES:
        frappe.throw(_('Invalid staff position roles.'), frappe.PermissionError)
    active = bool(position.active)
    parent, seen = position.get('parent_position'), {position.name}
    while parent:
        if parent in seen:
            frappe.throw(_('Position hierarchy contains a cycle.'), frappe.PermissionError)
        seen.add(parent)
        ancestor = frappe.db.get_value('LMS Staff Position', parent, ['parent_position', 'active'], as_dict=True)
        if not ancestor:
            active = False
            break
        active = active and bool(ancestor.active)
        parent = ancestor.parent_position
    return {'assignment': row.name, 'name': position.name, 'active': active,
            'permissions': permission_pairs(position.get('permissions') or []),
            'roles': roles, 'scope': position.course_scope or 'Owned'}


def _owned_course(user, course):
    if not isinstance(course, str) or not course:
        return False
    cache = _cache(); key = ('owned_course', user, course)
    if key not in cache:
        owner = frappe.db.get_value('LMS Course', course, 'owner')
        cache[key] = bool(owner == user or frappe.db.exists('Course Instructor', {
            'parent': course, 'parenttype': 'LMS Course', 'instructor': user}))
    return cache[key]


def assigned_capability(resource, action, course=None, user=None):
    """Return an explicit bool for assigned staff, None for legacy accounts.

    Credential integration calls this helper before its old Role Profile policy;
    this helper never calls credential_profiles, avoiding recursive checks.
    """
    user = user or frappe.session.user
    position = assigned_position(user)
    if position is None:
        return None
    if not position['active'] or (resource, action) not in position['permissions']:
        return False
    if resource == 'course_access' and course is not None and position['scope'] != 'All':
        return _owned_course(user, course)
    return True


def _legacy_credentials(user):
    if 'System Manager' in frappe.get_roles(user):
        return True
    if not frappe.get_meta('Role Profile').has_field('custom_can_manage_credentials'):
        return False
    return bool(frappe.db.sql('''select 1 from `tabRole Profile` p
      join `tabUser Role Profile` urp on urp.role_profile=p.name
      where p.custom_can_manage_credentials=1 and urp.parent=%s
      and urp.parenttype='User' and urp.parentfield='role_profiles' limit 1''', (user,)))


def has_capability(resource, action, course=None):
    if resource not in RESOURCES or action not in RESOURCES[resource]:
        return False
    actor = frappe.session.user
    if actor == 'Administrator':
        return True
    if not actor or actor == 'Guest':
        return False
    explicit = assigned_capability(resource, action, course, actor)
    if explicit is not None:
        return explicit
    if resource == 'credentials':
        return _legacy_credentials(actor)
    if 'Moderator' in frappe.get_roles(actor) and (resource, action) in LEGACY_MODERATOR:
        return True
    if (resource == 'course_access' and course is not None and 'Course Creator' in frappe.get_roles(actor)
            and action in RESOURCES['course_access']):
        return _owned_course(actor, course)
    return False


def require_capability(resource, action, course=None):
    if not has_capability(resource, action, course):
        frappe.throw(_('Your position does not permit this action.'), frappe.PermissionError)

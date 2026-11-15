"""Fail-closed staff administration until delegated positions are configured.

These checks add restrictions; they never replace Frappe document permissions.
Ordinary profile edits and new student accounts remain subject to those native
permissions. No request flag or ignore_permissions option bypasses this policy.
"""
import frappe
from frappe import _
from lms.lms.staff_policy import has_capability, require_capability, is_controlled_user_change


BASIC_ROLES = frozenset({'LMS Student'})
SECURITY_FIELDS = (
    'enabled', 'user_type', 'role_profile_name', 'module_profile',
    'restrict_ip', 'bypass_restrict_ip_check_if_2fa_enabled',
    'login_after', 'login_before',
)


def _actor():
    return getattr(frappe.session, 'user', None) or 'Guest'


def _deny():
    frappe.throw(_('You do not have permission to manage staff roles.'), frappe.PermissionError)


def _target(target):
    if not isinstance(target, str) or not target or target.strip() != target:
        _deny()
    return target


def can_manage_staff_roles(target=None):
    """UI affordance only; mutations must call their matching require helper."""
    if _actor() != 'Administrator':
        return False
    return target is None or (
        isinstance(target, str) and bool(target) and target.strip() == target and target != 'Guest'
    )


def require_role_change(target, role=None):
    """Require explicit authority for any grant/revocation, including self edits.

    Roles held by an actor are not a delegation policy: allowing an actor to
    pass along their own Moderator or System Manager role would let another
    person grant powers back to them. Until a bounded delegation policy exists,
    only Administrator can use this operation.
    """
    target = _target(target)
    if role is not None and (not isinstance(role, str) or not role.strip()):
        _deny()
    if target == 'Guest' or _actor() != 'Administrator':
        _deny()


def require_staff_delete(target):
    """Protect built-in accounts and require staff-deletion authority."""
    target = _target(target)
    if target in ('Administrator', 'Guest') or target == _actor():
        _deny()
    if _actor() != 'Administrator':
        _deny()


def user_delete_permission(doc, user=None, permission_type=None, ptype=None, **kwargs):
    """Deny-only User hook; ordinary read/write permissions remain native."""
    if (permission_type or ptype) != 'delete':
        return None
    actor = user or _actor()
    if doc.name in ('Administrator', 'Guest', actor) or actor != 'Administrator':
        return False
    return None


def _members(doc, field, key):
    rows = doc.get(field) or []
    if not isinstance(rows, (list, tuple)):
        _deny()
    values = []
    for row in rows:
        if not hasattr(row, 'get'):
            _deny()
        value = row.get(key)
        if not isinstance(value, str) or not value.strip():
            _deny()
        values.append(value)
    return frozenset(values)


def _value(doc, field):
    value = doc.get(field)
    # Frappe commonly materializes unfilled Data fields as either None or ''.
    return None if value is None or value == '' else value


def check_user_role_edits(doc, method=None):
    """User validate hook: guard parent saves and REST child-table updates.

    Frappe populates roles from Role Profiles in User.validate before app
    validate hooks run, so comparing both role and profile membership catches
    direct role edits, profile substitutions and their resulting role changes.
    Reordering unchanged child rows is allowed. A missing persisted snapshot
    is an error, not permission to accept an unknown previous role set.
    """
    if _actor() == 'Administrator':
        return

    if is_controlled_user_change(doc):
        return

    roles = _members(doc, 'roles', 'role')
    profiles = _members(doc, 'role_profiles', 'role_profile')
    if doc.is_new():
        if (roles - BASIC_ROLES or profiles or _value(doc, 'role_profile_name')
                or _value(doc, 'user_type') not in (None, 'Website User')
                or _value(doc, 'module_profile')):
            _deny()
        # The parent insert still has to pass Frappe create permissions. This
        # path permits student signup/import, not creation of staff positions.
        return

    before = doc.get_doc_before_save()
    if before is None:
        _deny()
    changed = (
        roles != _members(before, 'roles', 'role')
        or profiles != _members(before, 'role_profiles', 'role_profile')
        or _members(doc, 'block_modules', 'module') != _members(before, 'block_modules', 'module')
        or any(_value(doc, field) != _value(before, field) for field in SECURITY_FIELDS)
    )
    if changed:
        require_role_change(doc.name)


def check_evaluator_role_edits(doc, method=None):
    """Guard evaluator side effects before the controller changes Has Role.

    Call at the start of CourseEvaluator.validate_evaluator_role and on_trash,
    or wire the validation path to before_validate. A validate event hook alone
    would run after the controller has already granted the role.

    A person who already has Batch Evaluator may create their availability
    record; that creates no new role. Native document/API permission checks
    continue to control who may edit the availability itself.
    """
    target = _target(doc.get('evaluator'))
    if _actor() == 'Administrator':
        return
    if method == 'on_trash':
        require_role_change(target, 'Batch Evaluator')
        return
    if not doc.is_new():
        before = doc.get_doc_before_save()
        if before is None or before.get('evaluator') != target:
            require_role_change(target, 'Batch Evaluator')
    if not frappe.db.exists('Has Role', {'parent': target, 'parenttype': 'User', 'role': 'Batch Evaluator'}):
        require_role_change(target, 'Batch Evaluator')


def check_role_definition_edits(doc, method=None):
    """Role/Role Profile event guard; delegation is not enabled by role name."""
    if _actor() != 'Administrator':
        _deny()

"""Bounded employee/position administration, separate from learner cards."""
from contextlib import contextmanager
import hashlib
import json

import frappe
from frappe import _
from frappe.utils import cint, now_datetime

from lms.lms.staff_policy import (
    NATIVE_ROLES, RESOURCES, _controlled_user_write, assigned_position,
    clear_policy_cache, has_capability, permission_pairs, require_capability,
)


def _deny():
    frappe.throw(_('Your position does not permit this staff change.'), frappe.PermissionError)


def _admin():
    return frappe.session.user == 'Administrator'


def _lock():
    """Hold the per-site policy lock until transaction commit or rollback."""
    if getattr(frappe.flags, '_lms_staff_policy_locked', False):
        return
    key = 'lms-staff:' + hashlib.sha256(frappe.local.site.encode()).hexdigest()[:32]
    if frappe.db.sql('select GET_LOCK(%s,0)', (key,))[0][0] != 1:
        frappe.throw(_('Staff settings are being changed. Please try again.'), frappe.ValidationError)
    frappe.flags._lms_staff_policy_locked = True
    clear_policy_cache()

    def release():
        frappe.db.sql('select RELEASE_LOCK(%s)', (key,))
        frappe.flags._lms_staff_policy_locked = False
        clear_policy_cache()
    frappe.db.after_commit.add(release)
    frappe.db.after_rollback.add(release)


def _graph():
    rows = frappe.get_all('LMS Staff Position', fields=['name', 'parent_position', 'active'], limit_page_length=0)
    return {r.name: r.parent_position or None for r in rows}


def is_descendant(name, ancestor, graph, *, include_self=False):
    if not name or not ancestor:
        return False
    if name == ancestor:
        return include_self
    seen = set()
    while name:
        if name in seen:
            frappe.throw(_('Position hierarchy contains a cycle.'), frappe.ValidationError)
        seen.add(name)
        name = graph.get(name)
        if name == ancestor:
            return True
    return False


def _actor_position():
    current = assigned_position()
    if not current or not current['active']:
        _deny()
    return current


def _scope_target(name, graph):
    if _admin():
        return
    own = _actor_position()['name']
    if not is_descendant(name, own, graph):
        _deny()


def _roles(doc):
    rows = doc.get('native_roles') or []
    if not isinstance(rows,(list,tuple)) or any(not hasattr(row,'get') for row in rows):
        frappe.throw(_('Invalid platform roles.'), frappe.ValidationError)
    values = [row.get('role') for row in rows]
    if any(not isinstance(role,str) for role in values):
        frappe.throw(_('Invalid platform roles.'), frappe.ValidationError)
    roles = frozenset(values)
    if (not roles <= NATIVE_ROLES
            or len(rows) != len(roles) or 'LMS Student' not in roles):
        frappe.throw(_('Select supported LMS roles, including LMS Student.'), frappe.ValidationError)
    return roles


def _position_active(name, graph):
    seen = set()
    while name:
        if name in seen:
            frappe.throw(_('Position hierarchy contains a cycle.'), frappe.ValidationError)
        seen.add(name)
        if not frappe.db.get_value('LMS Staff Position', name, 'active'):
            return False
        name = graph.get(name)
    return True


def validate_position_document(doc, method=None):
    _lock()
    require_capability('positions', 'create' if doc.is_new() else 'write')
    if not isinstance(doc.title, str) or not doc.title.strip() or len(doc.title) > 140:
        frappe.throw(_('Position title must contain 1 to 140 characters.'), frappe.ValidationError)
    doc.title = doc.title.strip()
    if doc.course_scope not in ('Owned', 'All'):
        frappe.throw(_('Invalid course scope.'), frappe.ValidationError)
    rights, roles = permission_pairs(doc.get('permissions') or []), _roles(doc)
    graph = _graph()
    parent = doc.parent_position or None
    if parent is not None and not isinstance(parent,str):
        frappe.throw(_('Invalid parent position.'), frappe.ValidationError)
    if parent and parent not in graph:
        frappe.throw(_('Parent position does not exist.'), frappe.ValidationError)
    if parent == doc.name or (parent and is_descendant(parent, doc.name, graph, include_self=True)):
        frappe.throw(_('Position hierarchy cannot contain a cycle.'), frappe.ValidationError)
    if not _admin():
        actor = _actor_position()
        if not doc.is_new():
            _scope_target(doc.name, graph)
        if not parent or not is_descendant(parent, actor['name'], graph, include_self=True):
            _deny()
        if not rights <= actor['permissions'] or not roles <= actor['roles']:
            _deny()
        if actor['scope'] != 'All' and doc.course_scope == 'All':
            _deny()
    if parent:
        parent_doc = frappe.get_doc('LMS Staff Position', parent)
        if (not rights <= permission_pairs(parent_doc.permissions or []) or not roles <= _roles(parent_doc)
                or (parent_doc.course_scope != 'All' and doc.course_scope == 'All')):
            frappe.throw(_('A position cannot exceed its parent permissions.'), frappe.ValidationError)
    # Lowering a ceiling must not silently leave stronger subordinate positions.
    for child in frappe.get_all('LMS Staff Position', filters={'parent_position': doc.name}, pluck='name', limit_page_length=0):
        child_doc = frappe.get_doc('LMS Staff Position', child)
        if (not permission_pairs(child_doc.permissions or []) <= rights or not _roles(child_doc) <= roles
                or (doc.course_scope != 'All' and child_doc.course_scope == 'All')):
            frappe.throw(_('Update subordinate positions before reducing their parent permissions.'), frappe.ValidationError)
    doc.changed_by, doc.changed_at = frappe.session.user, now_datetime()


def validate_position_delete(doc, method=None):
    _lock(); require_capability('positions', 'delete'); _scope_target(doc.name, _graph())
    if (frappe.db.exists('LMS Staff Position', {'parent_position': doc.name})
            or frappe.db.exists('LMS Staff Assignment', {'position': doc.name})):
        frappe.throw(_('A position with subordinates or employee history cannot be deleted. Disable it instead.'), frappe.ValidationError)


@contextmanager
def _assignment_write(user, position, active):
    previous = getattr(frappe.flags, '_lms_staff_assignment_write', None)
    # An object identity/token in request-local server state, never doc.flags.
    token = _AssignmentWrite(frappe.session.user, user, position, int(active))
    frappe.flags._lms_staff_assignment_write = token
    try:
        yield
    finally:
        frappe.flags._lms_staff_assignment_write = previous


class _AssignmentWrite:
    def __init__(self, actor, user, position, active):
        self.actor, self.user, self.position, self.active = actor, user, position, active


def _can_target_user(user, position, *, current=None, require_active=True):
    if user in ('Administrator', 'Guest') or (not _admin() and user == frappe.session.user):
        _deny()
    graph = _graph()
    if position not in graph or (require_active and not _position_active(position, graph)):
        frappe.throw(_('Choose an active staff position.'), frappe.ValidationError)
    if not _admin():
        _scope_target(position, graph)
        if current:
            _scope_target(current.position, graph)
        elif frappe.db.exists('User', user):
            held = set(frappe.get_roles(user)) - {'All', 'Guest', 'LMS Student'}
            if held:
                # Existing unassigned staff must first be placed by Administrator.
                _deny()


def validate_assignment_document(doc, method=None):
    _lock()
    before = None if doc.is_new() else doc.get_doc_before_save()
    action = 'create' if doc.is_new() else ('delete' if not cint(doc.active) and before and cint(before.active) else 'write')
    require_capability('staff', action)
    if not doc.is_new() and (before is None or before.user != doc.user):
        frappe.throw(_('An employee assignment cannot be transferred to another user.'), frappe.ValidationError)
    if before and before.position != doc.position:
        require_capability('staff', 'write')
    scope = getattr(frappe.flags, '_lms_staff_assignment_write', None)
    if not _admin() and (not isinstance(scope, _AssignmentWrite) or scope.actor != frappe.session.user
            or (scope.user, scope.position, scope.active) != (doc.user, doc.position, cint(doc.active))):
        _deny()
    if not cint(doc.active):
        require_capability('staff', 'delete')
    _can_target_user(doc.user, doc.position, current=before, require_active=bool(cint(doc.active)))
    duplicates = frappe.get_all('LMS Staff Assignment', filters={'user': doc.user}, pluck='name', limit_page_length=2)
    if any(name != doc.name for name in duplicates):
        frappe.throw(_('This employee already has an assignment.'), frappe.ValidationError)
    doc.assigned_by, doc.assigned_at = frappe.session.user, now_datetime()


def prevent_assignment_delete(doc, method=None):
    frappe.throw(_('Disable the employee instead of deleting their assignment history.'), frappe.PermissionError)


def _sync_user(assignment):
    doc = frappe.get_doc('User', assignment.user)
    raw_roles = {r.role for r in (doc.roles or [])}
    if not raw_roles <= NATIVE_ROLES:
        frappe.throw(_('Remove technical roles in the administrator console before assigning a bounded staff position.'), frappe.ValidationError)
    position = frappe.get_doc('LMS Staff Position', assignment.position)
    effective = cint(assignment.active) and _position_active(position.name, _graph())
    desired = _roles(position) if effective else frozenset({'LMS Student'})
    enabled = 1 if cint(assignment.active) else 0
    with _controlled_user_write(doc.name, desired, enabled):
        doc.set('roles', [{'role': role} for role in sorted(desired)])
        doc.set('role_profiles', []); doc.role_profile_name = None
        doc.enabled = enabled
        doc.save(ignore_permissions=True)
    frappe.clear_cache(user=doc.name)
    clear_policy_cache()


def assignment_updated(doc, method=None):
    _sync_user(doc)


def position_updated(doc, method=None):
    clear_policy_cache()
    before = doc.get_doc_before_save()
    if before and (_roles(before) != _roles(doc) or cint(before.active) != cint(doc.active)
                   or before.parent_position != doc.parent_position):
        graph = _graph()
        affected = [name for name in graph if is_descendant(name,doc.name,graph,include_self=True)]
        for row in frappe.get_all('LMS Staff Assignment', filters={'position': ['in',affected], 'active': 1}, fields=['user','position','active'], limit_page_length=0):
            _sync_user(row)


def _position_data(doc):
    graph = _graph()
    editable = has_capability('positions', 'write') and (_admin() or is_descendant(doc.name, _actor_position()['name'], graph))
    return {'name': doc.name, 'title': doc.title, 'parent_position': doc.parent_position,
            'active': bool(doc.active), 'course_scope': doc.course_scope,
            'permissions': [{'resource': r, 'action': a} for r, a in sorted(permission_pairs(doc.permissions or []))],
            'native_roles': sorted(_roles(doc)), 'can_edit': editable}


@frappe.whitelist()
def metadata():
    if not any(has_capability(r, 'read') for r in ('staff', 'positions')):
        _deny()
    graph = _graph(); own = None if _admin() else _actor_position()['name']
    positions = frappe.get_all('LMS Staff Position', fields=['name','title','parent_position','active'], order_by='title', limit_page_length=0)
    visible = [r for r in positions if _admin() or is_descendant(r.name, own, graph, include_self=True)]
    return {'resources': RESOURCES, 'native_roles': sorted(NATIVE_ROLES),
            'positions': [dict(r) for r in visible], 'own_position': own,
            'capabilities': {r: {a: has_capability(r,a) for a in actions} for r,actions in RESOURCES.items()}}


@frappe.whitelist()
def list_positions():
    require_capability('positions', 'read')
    graph = _graph(); own = None if _admin() else _actor_position()['name']
    names = [n for n in graph if _admin() or is_descendant(n, own, graph, include_self=True)]
    return [_position_data(frappe.get_doc('LMS Staff Position', name)) for name in names]


@frappe.whitelist(methods=['POST'])
def save_position(values):
    values = frappe.parse_json(values) if isinstance(values, str) else values
    allowed = {'name','title','parent_position','active','course_scope','permissions','native_roles'}
    if not isinstance(values, dict) or set(values) - allowed:
        frappe.throw(_('Invalid position data.'), frappe.ValidationError)
    if values.get('active', 1) not in (0,1,False,True,'0','1'):
        frappe.throw(_('Invalid position status.'), frappe.ValidationError)
    _lock()
    doc = frappe.get_doc('LMS Staff Position', values['name']) if values.get('name') else frappe.new_doc('LMS Staff Position')
    for key in ('title','parent_position','active','course_scope','permissions'):
        if key in values:
            doc.set(key, values[key])
    if 'native_roles' in values:
        if not isinstance(values['native_roles'], list) or any(not isinstance(r,str) for r in values['native_roles']):
            frappe.throw(_('Invalid platform roles.'), frappe.ValidationError)
        doc.set('native_roles', [{'role': r} for r in values['native_roles']])
    doc.save(ignore_permissions=True)
    clear_policy_cache()
    return _position_data(doc)


@frappe.whitelist(methods=['POST'])
def delete_position(name):
    _lock(); require_capability('positions', 'delete')
    frappe.delete_doc('LMS Staff Position', name, ignore_permissions=True)
    clear_policy_cache()
    return {'deleted': True}


def _page(page, page_size):
    if isinstance(page,bool) or isinstance(page_size,bool):
        frappe.throw(_('Invalid page.'), frappe.ValidationError)
    try: page, page_size = int(page), int(page_size)
    except (TypeError, ValueError): frappe.throw(_('Invalid page.'), frappe.ValidationError)
    if page < 1 or page_size not in (25, 50, 100):
        frappe.throw(_('Invalid page.'), frappe.ValidationError)
    return page, page_size


@frappe.whitelist()
def list_employees(page=1, page_size=50, search=''):
    require_capability('staff', 'read')
    page, page_size = _page(page, page_size)
    if not isinstance(search,str) or len(search)>140:
        frappe.throw(_('Invalid search.'), frappe.ValidationError)
    conditions = ["u.name not in ('Administrator','Guest')", "(a.name is not null or exists (select 1 from `tabHas Role` r where r.parent=u.name and r.parenttype='User' and r.role in ('Moderator','Course Creator','Batch Evaluator','System Manager')))"]
    args = []
    if not _admin():
        own = _actor_position()['name']; graph = _graph()
        allowed = [name for name in graph if is_descendant(name, own, graph)]
        if not allowed: return {'rows': [], 'total': 0, 'page': page, 'page_size': page_size}
        conditions.append('a.position in ('+','.join(['%s']*len(allowed))+')'); args.extend(allowed)
    if search.strip():
        conditions.append('(u.full_name like %s or u.email like %s)'); args.extend(['%'+search.strip()+'%']*2)
    query = ' from `tabUser` u left join `tabLMS Staff Assignment` a on a.user=u.name left join `tabLMS Staff Position` p on p.name=a.position where '+' and '.join(conditions)
    total = frappe.db.sql('select count(*)'+query, args)[0][0]
    rows = frappe.db.sql('select u.name,u.full_name,u.email,u.enabled,a.name as assignment,a.position,a.active,p.title as position_title'+query+' order by u.full_name,u.name limit %s offset %s', args+[page_size,(page-1)*page_size], as_dict=True)
    return {'rows': rows, 'total': total, 'page': page, 'page_size': page_size}


@frappe.whitelist(methods=['POST'])
def save_employee(user, position, active=1, first_name=None, last_name=None):
    _lock()
    if (not isinstance(user,str) or not user or len(user)>140 or user.strip()!=user
            or not isinstance(position,str) or not position or active not in (0,1,False,True,'0','1')
            or any(value is not None and (not isinstance(value,str) or len(value)>140) for value in (first_name,last_name))):
        frappe.throw(_('Invalid employee data.'), frappe.ValidationError)
    active = cint(active)
    rows = frappe.get_all('LMS Staff Assignment', filters={'user': user}, pluck='name', limit_page_length=2)
    if len(rows)>1: _deny()
    current = frappe.get_doc('LMS Staff Assignment', rows[0]) if rows else None
    action = 'create' if current is None else ('delete' if not active and cint(current.active) else 'write')
    require_capability('staff', action)
    _can_target_user(user, position, current=current, require_active=bool(active))
    if not frappe.db.exists('User', user):
        if not first_name or not first_name.strip():
            frappe.throw(_('First name is required for a new employee.'), frappe.ValidationError)
        doc = frappe.get_doc({'doctype':'User','email':user,'first_name':first_name.strip(),
                             'last_name':last_name or '', 'send_welcome_email':False,
                             'user_type':'Website User','roles':[{'role':'LMS Student'}]})
        doc.insert(ignore_permissions=True)
        user = doc.name
    assignment = current or frappe.new_doc('LMS Staff Assignment')
    assignment.user, assignment.position, assignment.active = user, position, active
    with _assignment_write(user, position, active):
        assignment.save(ignore_permissions=True)
    clear_policy_cache()
    frappe.logger('lms_staff').info({'action':'employee_assignment_changed','actor':frappe.session.user,'target':user,'position':position,'active':active})
    return {'saved': True, 'assignment': assignment.name}

"""Real-controller smoke checks for an isolated, initialized Frappe stage.

Never run against a production site. Synthetic fixtures remain in the stage
with a unique prefix. The result contains booleans only; no names, addresses,
passwords, role assignments or database configuration are returned.
"""
import hashlib
import uuid

import frappe


def run():
    site = getattr(frappe.local, 'site', '')
    if not isinstance(site, str) or not site.endswith('.local') or 'stage' not in site:
        raise RuntimeError('isolated_stage_required')

    from lms.lms.api import save_role
    from lms.lms.staff_policy import NATIVE_ROLES, RESOURCES, clear_policy_cache, has_capability
    from lms.lms.staff_positions import save_employee, save_position

    checks = {name: False for name in (
        'fixtures_ready', 'position_policy_applied', 'credential_ceiling',
        'self_role_denied', 'raw_user_role_denied', 'self_position_denied',
        'descendant_position_created', 'actor_ceiling_denied', 'parent_ceiling_denied',
        'generic_assignment_denied', 'descendant_assignment_saved',
        'self_assignment_denied', 'outside_subtree_denied',
        'employee_deactivated_without_deletion', 'parent_reduction_denied',
        'lock_released_after_transactions',
    )}
    previous_user = frappe.session.user
    prefix = 'staff-smoke-' + uuid.uuid4().hex[:10]
    manager = prefix + '-manager@example.invalid'
    learner = prefix + '-learner@example.invalid'
    outsider_user = prefix + '-outside@example.invalid'
    lock_key = 'lms-staff:' + hashlib.sha256(site.encode()).hexdigest()[:32]
    releases = []

    def actor(name):
        frappe.set_user(name)
        clear_policy_cache()

    def released():
        releases.append(frappe.db.sql('select IS_FREE_LOCK(%s)', (lock_key,))[0][0] == 1)

    def denied(function):
        result = False
        try:
            function()
        except (frappe.PermissionError, frappe.ValidationError):
            result = True
        except Exception:
            # An unrelated validation/implementation failure is not an access
            # control success. The aggregate remains false and the stage data
            # is rolled back without exposing the exception's personal fields.
            result = False
        finally:
            frappe.db.rollback()
            clear_policy_cache()
            released()
        return result

    def position(title, parent, permissions, roles=('LMS Student',), scope='Owned'):
        return save_position({'title': prefix + '-' + title, 'parent_position': parent,
            'active': 1, 'course_scope': scope,
            'permissions': [{'resource': r, 'action': a} for r, a in permissions],
            'native_roles': sorted(roles)})

    def held_roles(user):
        return frozenset(frappe.get_all('Has Role', filters={'parent': user, 'parenttype': 'User'}, pluck='role'))

    try:
        actor('Administrator')
        for email, label in ((manager, 'Manager'), (learner, 'Learner'), (outsider_user, 'Outside')):
            frappe.get_doc({'doctype': 'User', 'email': email, 'first_name': prefix + '-' + label,
                'user_type': 'Website User', 'send_welcome_email': False,
                'roles': [{'role': 'LMS Student'}]}).insert(ignore_permissions=True)
        all_rights = [(r, a) for r, actions in RESOURCES.items() for a in actions]
        root = position('root', None, all_rights, roles=NATIVE_ROLES, scope='All')
        manager_rights = [(r, a) for r in ('contacts', 'course_access', 'staff', 'positions') for a in RESOURCES[r]]
        parent = position('manager', root['name'], manager_rights, roles=('LMS Student', 'Moderator'))
        narrow = position('narrow', parent['name'], [('contacts', 'read')])
        outside = position('outside', root['name'], [('contacts', 'read')])
        contact = frappe.get_doc({'doctype': 'Contact', 'first_name': prefix + '-learner', 'user': learner})
        contact.insert(ignore_permissions=True)
        contact_name = contact.name
        save_employee(manager, parent['name'])
        frappe.db.commit(); clear_policy_cache(); released()
        checks['fixtures_ready'] = True

        actor(manager)
        initial_roles = held_roles(manager)
        checks['position_policy_applied'] = bool(has_capability('staff', 'create') and 'Moderator' in initial_roles)
        checks['credential_ceiling'] = not any(has_capability('credentials', action) for action in RESOURCES['credentials'])
        checks['self_role_denied'] = denied(lambda: save_role(manager, 'Course Creator', 1)) and held_roles(manager) == initial_roles

        def direct_user_grant():
            user = frappe.get_doc('User', manager)
            user.append('roles', {'role': 'System Manager'})
            user.save(ignore_permissions=True)
        checks['raw_user_role_denied'] = denied(direct_user_grant) and held_roles(manager) == initial_roles

        own_data = {key: parent[key] for key in ('name', 'title', 'parent_position', 'active', 'course_scope', 'permissions', 'native_roles')}
        checks['self_position_denied'] = denied(lambda: save_position(own_data))

        delegated = position('delegated', parent['name'], [('contacts', 'read')])
        frappe.db.commit(); clear_policy_cache(); released()
        checks['descendant_position_created'] = bool(frappe.db.exists('LMS Staff Position', delegated['name']))
        checks['actor_ceiling_denied'] = denied(lambda: position('too-strong', parent['name'], [('credentials', 'read')]))
        checks['parent_ceiling_denied'] = denied(lambda: position('above-parent', narrow['name'], [('contacts', 'read'), ('contacts', 'write')]))

        def direct_assignment():
            frappe.get_doc({'doctype': 'LMS Staff Assignment', 'user': learner,
                'position': delegated['name'], 'active': 1}).insert(ignore_permissions=True)
        checks['generic_assignment_denied'] = denied(direct_assignment)

        save_employee(learner, delegated['name'])
        frappe.db.commit(); clear_policy_cache(); released()
        assignment = frappe.db.get_value('LMS Staff Assignment', {'user': learner}, ['position', 'active'], as_dict=True)
        checks['descendant_assignment_saved'] = bool(assignment and assignment.position == delegated['name'] and assignment.active)
        checks['self_assignment_denied'] = denied(lambda: save_employee(manager, delegated['name']))
        checks['outside_subtree_denied'] = denied(lambda: save_employee(outsider_user, outside['name']))

        save_employee(learner, delegated['name'], active=0)
        frappe.db.commit(); clear_policy_cache(); released()
        checks['employee_deactivated_without_deletion'] = bool(
            frappe.db.exists('User', learner) and frappe.db.exists('Contact', contact_name)
            and not frappe.db.get_value('User', learner, 'enabled')
            and not frappe.db.get_value('LMS Staff Assignment', {'user': learner}, 'active')
        )
        actor('Administrator')
        reduced = dict(own_data, permissions=[])
        checks['parent_reduction_denied'] = denied(lambda: save_position(reduced))
        checks['lock_released_after_transactions'] = bool(releases and all(releases))
    except Exception:
        frappe.db.rollback()
        clear_policy_cache()
    finally:
        frappe.db.rollback()
        frappe.set_user(previous_user)
        clear_policy_cache()
    checks['all_passed'] = all(checks.values())
    return checks

"""Policy boundary tests without a database or any account mutations."""
import importlib.util
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import patch


class UserDoc(dict):
    def __init__(self, name='target@example.test', *, new=False, before=None, **values):
        super().__init__(values)
        self.name, self._new, self._before = name, new, before

    def is_new(self):
        return self._new

    def get_doc_before_save(self):
        return self._before


def user(**values):
    defaults = {'roles': [{'role': 'LMS Student'}], 'role_profiles': [],
                'enabled': 1, 'user_type': 'Website User'}
    defaults.update(values)
    return UserDoc(**defaults)


class StaffAuthorityTests(unittest.TestCase):
    def setUp(self):
        f = types.ModuleType('frappe')
        f._ = lambda s: s
        f.session = types.SimpleNamespace(user='moderator@example.test')
        f.PermissionError = PermissionError
        f.throw = lambda message, exc: (_ for _ in ()).throw(exc(message))
        self.role_exists = False
        f.db = types.SimpleNamespace(exists=lambda *a, **kw: self.role_exists)
        self.frappe = f
        policy = types.ModuleType('lms.lms.staff_policy')
        policy.has_capability = lambda *args, **kwargs: False
        policy.require_capability = lambda *args, **kwargs: (_ for _ in ()).throw(PermissionError())
        policy.is_controlled_user_change = lambda doc: False
        self.modules = patch.dict(sys.modules, {'frappe': f, 'lms.lms.staff_policy': policy})
        self.modules.start()
        self.addCleanup(self.modules.stop)
        spec = importlib.util.spec_from_file_location('staff_authority_under_test', Path(__file__).with_name('staff_authority.py'))
        self.module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.module)

    def test_non_admin_staff_grants_and_revocations_are_closed(self):
        for actor in ('moderator@example.test', 'manager@example.test', 'student@example.test', 'Guest'):
            self.frappe.session.user = actor
            for target in (actor, 'another@example.test', 'Administrator'):
                for role in ('Moderator', 'System Manager', 'Batch Evaluator', None):
                    with self.subTest(actor=actor, target=target, role=role):
                        self.assertFalse(self.module.can_manage_staff_roles(target))
                        with self.assertRaises(PermissionError): self.module.require_role_change(target, role)

    def test_administrator_can_manage_ordinary_staff(self):
        self.frappe.session.user = 'Administrator'
        self.assertTrue(self.module.can_manage_staff_roles())
        self.assertTrue(self.module.can_manage_staff_roles('target@example.test'))
        self.module.require_role_change('target@example.test', 'Moderator')
        self.module.require_staff_delete('target@example.test')

    def test_built_in_accounts_are_not_deletable(self):
        for actor in ('Administrator', 'moderator@example.test'):
            self.frappe.session.user = actor
            for target in ('Administrator', 'Guest', actor):
                with self.assertRaises(PermissionError): self.module.require_staff_delete(target)

    def test_non_admin_cannot_delete_another_user(self):
        with self.assertRaises(PermissionError): self.module.require_staff_delete('target@example.test')

    def test_malformed_targets_are_not_authorized_even_for_admin(self):
        self.frappe.session.user = 'Administrator'
        for target in ('', ' x ', None, 1, True):
            if target is not None:
                self.assertFalse(self.module.can_manage_staff_roles(target))
            with self.assertRaises(PermissionError): self.module.require_role_change(target)

    def test_self_profile_edit_preserves_existing_staff_roles(self):
        old = user(name=self.frappe.session.user, roles=[{'role': 'Moderator'}], user_type='System User')
        new = user(name=self.frappe.session.user, before=old, roles=[{'role': 'Moderator'}], user_type='System User',
                   first_name='Changed', bio='New profile text', language='ru', new_password='reset-password')
        self.module.check_user_role_edits(new)

    def test_parent_save_cannot_add_or_remove_roles(self):
        old = user()
        for changed in ([{'role': 'LMS Student'}, {'role': 'Moderator'}], []):
            with self.assertRaises(PermissionError): self.module.check_user_role_edits(user(before=old, roles=changed))

    def test_profile_assignment_and_legacy_assignment_are_protected(self):
        old = user()
        for changes in ({'role_profiles': [{'role_profile': 'Privileged position'}]},
                        {'role_profile_name': 'Privileged position'}):
            with self.assertRaises(PermissionError): self.module.check_user_role_edits(user(before=old, **changes))

    def test_reordering_identical_role_membership_is_allowed(self):
        old = user(roles=[{'role': 'Moderator'}, {'role': 'LMS Student'}])
        new = user(before=old, roles=[{'role': 'LMS Student'}, {'role': 'Moderator'}])
        self.module.check_user_role_edits(new)

    def test_changed_account_security_is_protected(self):
        old = user()
        for changes in ({'enabled': 0}, {'user_type': 'System User'}, {'module_profile': 'More modules'},
                        {'restrict_ip': '127.0.0.1'}, {'block_modules': [{'module': 'Core'}]}):
            with self.assertRaises(PermissionError): self.module.check_user_role_edits(user(before=old, **changes))

    def test_empty_data_field_normalization_does_not_block_profile_save(self):
        self.module.check_user_role_edits(user(before=user(module_profile=None), module_profile=''))

    def test_student_insert_works_but_staff_insert_does_not(self):
        self.module.check_user_role_edits(user(new=True))
        self.module.check_user_role_edits(user(new=True, roles=[]))
        for changes in ({'roles': [{'role': 'Moderator'}]}, {'user_type': 'System User'},
                        {'role_profiles': [{'role_profile': 'Privileged position'}]}):
            with self.assertRaises(PermissionError): self.module.check_user_role_edits(user(new=True, **changes))

    def test_admin_import_is_not_blocked(self):
        self.frappe.session.user = 'Administrator'
        self.module.check_user_role_edits(user(new=True, roles=[{'role': 'Moderator'}], user_type='System User'))

    def test_unknown_previous_state_and_malformed_tables_fail_closed(self):
        for new in (user(), user(before=user(), roles='Moderator'), user(before=user(), roles=[{}])):
            with self.assertRaises(PermissionError): self.module.check_user_role_edits(new)

    def test_evaluator_creation_cannot_grant_missing_role(self):
        doc = UserDoc(new=True, evaluator=self.frappe.session.user)
        with self.assertRaises(PermissionError): self.module.check_evaluator_role_edits(doc)
        self.role_exists = True
        self.module.check_evaluator_role_edits(doc)

    def test_existing_evaluator_can_edit_schedule_without_role_changes(self):
        self.role_exists = True
        before = UserDoc(evaluator=self.frappe.session.user)
        doc = UserDoc(before=before, evaluator=self.frappe.session.user, schedule=[{'day': 'Monday'}])
        self.module.check_evaluator_role_edits(doc)

    def test_evaluator_reassignment_and_deletion_require_role_authority(self):
        self.role_exists = True
        doc = UserDoc(before=UserDoc(evaluator='other@example.test'), evaluator=self.frappe.session.user)
        with self.assertRaises(PermissionError): self.module.check_evaluator_role_edits(doc)
        with self.assertRaises(PermissionError): self.module.check_evaluator_role_edits(doc, 'on_trash')

    def test_role_definitions_cannot_change_self_authority_through_a_profile(self):
        doc = UserDoc(roles=[{'role': 'System Manager'}])
        with self.assertRaises(PermissionError): self.module.check_role_definition_edits(doc)
        self.frappe.session.user = 'Administrator'
        self.module.check_role_definition_edits(doc)

    def test_user_delete_hook_only_subtracts_permissions(self):
        doc=UserDoc()
        self.assertIsNone(self.module.user_delete_permission(doc,permission_type='read'))
        self.assertFalse(self.module.user_delete_permission(doc,permission_type='delete'))
        self.assertIsNone(self.module.user_delete_permission(doc,user='Administrator',ptype='delete'))
        self.assertFalse(self.module.user_delete_permission(UserDoc(name='Administrator'),user='Administrator',ptype='delete'))


if __name__ == '__main__': unittest.main()

"""Legacy URLs/methods use exactly the same authorization as the new card."""
import importlib.util
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import Mock, patch


class ContactResolverTest(unittest.TestCase):
    def setUp(self):
        f = types.ModuleType('frappe')
        f._ = lambda value: value
        f.whitelist = lambda *a, **kw: lambda func: func
        f.PermissionError = PermissionError
        f.ValidationError = ValueError
        f.throw = lambda message, exc: (_ for _ in ()).throw(exc(message))
        workspace = types.ModuleType('lms.lms.contact_workspace')
        workspace.get_card = Mock(return_value={'kind': 'User', 'name': 'member@example.test'})
        workspace.save_card = Mock(return_value={'saved': True})
        workspace.resolve_source_id = Mock(return_value={'kind': 'Contact', 'name': 'contact-one'})
        workspace.list_person_courses = Mock(return_value={'rows': [{'course': 'course-one'}]})
        self.w = workspace
        self.patch = patch.dict(sys.modules, {'frappe': f, 'lms.lms.contact_workspace': workspace})
        self.patch.start()
        spec = importlib.util.spec_from_file_location('legacy_contact_test', Path(__file__).with_name('avo_contact_card.py'))
        self.m = importlib.util.module_from_spec(spec);spec.loader.exec_module(self.m)

    def tearDown(self): self.patch.stop()

    def test_card_and_save_legacy_methods_delegate_to_workspace_permissions(self):
        self.assertEqual(self.m.get_card('User', 'member@example.test')['kind'], 'User')
        self.w.get_card.assert_called_once_with('User', 'member@example.test')
        values = {'first_name': 'Person'}
        self.assertEqual(self.m.save_card('Contact', 'contact-one', values), {'saved': True})
        self.w.save_card.assert_called_once_with('Contact', 'contact-one', values)

    def test_numeric_legacy_resolver_preserves_contact_identity(self):
        self.assertEqual(self.m.resolve_source_id('42'), {'kind': 'Contact', 'name': 'contact-one'})
        self.w.resolve_source_id.assert_called_once_with('42')

    def test_permission_failure_is_not_swallowed_or_retried_through_another_path(self):
        self.w.resolve_source_id.side_effect = PermissionError('denied')
        with self.assertRaises(PermissionError): self.m.resolve_source_id('42')
        self.w.resolve_source_id.assert_called_once()
        self.w.save_card.side_effect = PermissionError('denied')
        with self.assertRaises(PermissionError): self.m.save_card('User', 'member@example.test', {})

    def test_course_legacy_method_returns_only_the_authorized_page(self):
        self.assertEqual(self.m.courses_for_user('member@example.test'), [{'course': 'course-one'}])
        self.w.list_person_courses.assert_called_once_with('User', 'member@example.test', page=1, page_size=200)


if __name__ == '__main__': unittest.main()

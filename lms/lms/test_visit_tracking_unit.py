import importlib.util
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import Mock, patch


class Row(dict):
    __getattr__ = dict.get


class VisitTrackingTests(unittest.TestCase):
    def setUp(self):
        self.f = types.ModuleType('frappe')
        self.f.whitelist = lambda *a, **kw: lambda f: f
        self.f.session = Row(user='student', data={})
        self.f.get_roles = Mock(return_value=['LMS Student'])
        self.f.PermissionError = PermissionError
        self.f.throw = lambda msg, exc: (_ for _ in ()).throw(exc(msg))
        self.f.db = Row(get_value=Mock(return_value='course'), exists=Mock(return_value=False), sql=Mock())
        self.f.get_doc = Mock(return_value=Row(insert=Mock()))
        permissions = types.ModuleType('lms.lms.permissions')
        permissions.can_access_lesson = Mock(return_value=True)
        permissions.get_lesson_gate = Mock(return_value=(set(), None))
        utils = types.ModuleType('lms.lms.utils')
        utils.can_modify_course = Mock(return_value=False)
        utils.get_membership = Mock(return_value=True)
        fu = types.ModuleType('frappe.utils')
        fu.now_datetime = lambda: '2026-11-17 10:00:00'
        self.p = patch.dict(sys.modules, {'frappe': self.f, 'frappe.utils': fu,
            'lms.lms.permissions': permissions, 'lms.lms.utils': utils})
        self.p.start()
        spec = importlib.util.spec_from_file_location('visit_tracking_unit', Path(__file__).with_name('visit_tracking.py'))
        self.m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.m)

    def tearDown(self):
        self.p.stop()

    def test_impersonation_does_not_write_student_visit(self):
        self.f.session['data'] = {'impersonated_by': 'staff'}
        self.assertFalse(self.m.record_lesson_visit('course', 'lesson')['recorded'])
        self.f.db.sql.assert_not_called()
        self.f.get_doc.assert_not_called()

    def test_staff_preview_does_not_write_visit(self):
        self.f.get_roles.return_value = ['Moderator', 'LMS Student']
        self.assertFalse(self.m.record_lesson_visit('course', 'lesson')['recorded'])
        self.f.get_doc.assert_not_called()

    def test_verified_dates_are_recorded_for_learner_without_policy_switch(self):
        self.assertTrue(self.m.record_lesson_visit('course', 'lesson')['recorded'])
        record = self.f.get_doc.call_args.args[0]
        self.assertEqual(record['first_learner_visit_at'], '2026-11-17 10:00:00')
        self.assertEqual(record['last_learner_visit_at'], '2026-11-17 10:00:00')
        self.assertIn('COALESCE(first_learner_visit_at', self.f.db.sql.call_args.args[0])

    def test_historical_creation_is_not_reused_as_verified_visit(self):
        self.f.db.exists.return_value = True
        self.m.record_lesson_visit('course', 'lesson')
        self.f.get_doc.assert_not_called()
        self.assertEqual(self.f.db.sql.call_args.args[1][0], '2026-11-17 10:00:00')


if __name__ == '__main__':
    unittest.main()

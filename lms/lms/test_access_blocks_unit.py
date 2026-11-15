import importlib.util
from datetime import datetime
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import patch


class AccessBlocksTests(unittest.TestCase):
    def setUp(self):
        self.f = types.ModuleType('frappe')
        self.f._ = lambda value: value
        self.f.whitelist = lambda *a, **kw: lambda f: f
        self.f.local = types.SimpleNamespace()
        self.f.db = types.SimpleNamespace(table_exists=lambda _: True)
        self.f.get_all = lambda *a, **kw: []
        utils = types.ModuleType('frappe.utils')
        utils.get_datetime = lambda value: datetime.fromisoformat(value) if isinstance(value, str) else value
        utils.now_datetime = lambda: datetime(2026, 1, 1, 12)
        self.modules = patch.dict(sys.modules, {'frappe': self.f, 'frappe.utils': utils})
        self.modules.start()
        spec = importlib.util.spec_from_file_location('block_test_subject', Path(__file__).with_name('access_blocks.py'))
        self.mod = importlib.util.module_from_spec(spec);spec.loader.exec_module(self.mod)

    def tearDown(self):
        self.modules.stop()

    def test_permanent_course_block_overrides_any_lesson(self):
        self.assertTrue(self.mod.rows_block_access([{'active': 1}], 'lesson'))

    def test_timed_block_expires_at_exact_boundary(self):
        rows = [{'active': 1, 'blocked_until': '2026-01-01 12:00:00'}]
        self.assertTrue(self.mod.rows_block_access(rows, now='2026-01-01 11:59:59'))
        self.assertFalse(self.mod.rows_block_access(rows, now='2026-01-01 12:00:00'))

    def test_lesson_block_does_not_close_other_lessons_or_course(self):
        rows = [{'active': 1, 'lesson': 'lesson-a'}]
        self.assertTrue(self.mod.rows_block_access(rows, 'lesson-a'))
        self.assertFalse(self.mod.rows_block_access(rows, 'lesson-b'))
        self.assertFalse(self.mod.rows_block_access(rows))

    def test_reopened_and_expired_rows_do_not_override_schedule(self):
        self.assertFalse(self.mod.rows_block_access([{'active': 0}]))
        self.assertFalse(self.mod.rows_block_access([{'active': 1, 'blocked_until': '2025-01-01'}]))

    def test_missing_schema_does_not_change_existing_access(self):
        self.f.db.table_exists = lambda _: False
        self.assertFalse(self.mod.is_blocked('u', 'course', 'lesson'))

    def test_source_lookup_is_person_and_course_scoped_and_cached_per_request(self):
        calls = []
        self.f.get_all = lambda *a, **kw: calls.append(kw['filters']) or [{'active': 1}]
        self.assertTrue(self.mod.is_blocked('user-a', 'course-a', 'lesson-a'))
        self.assertTrue(self.mod.is_blocked('user-a', 'course-a', 'lesson-b'))
        self.assertTrue(self.mod.is_blocked('user-b', 'course-a', 'lesson-b'))
        self.assertEqual(calls, [
            {'member': 'user-a', 'course': 'course-a', 'active': 1},
            {'member': 'user-b', 'course': 'course-a', 'active': 1}])

    def test_override_is_checked_before_grants_or_policy_fallback(self):
        spec = importlib.util.spec_from_file_location('access_test_subject', Path(__file__).with_name('individual_access.py'))
        access = importlib.util.module_from_spec(spec);spec.loader.exec_module(access)
        with patch.dict(sys.modules, {'lms.lms.access_blocks': self.mod}), \
                patch.object(self.mod, 'is_blocked', return_value=True), \
                patch.object(access, 'policy_applies', side_effect=AssertionError('must not fall through')), \
                patch.object(access, 'grant_allows_lesson', side_effect=AssertionError('another grant must not allow access')):
            self.assertFalse(access.restrict_member_lesson(course='c',lesson='l',user='u',enrolled=True))


if __name__ == '__main__': unittest.main()

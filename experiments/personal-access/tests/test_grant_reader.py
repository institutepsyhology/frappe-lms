"""Grant-reader checks with a fake database, not live Frappe integration tests."""

import importlib.util
import sys
import types
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[3]
NOW = datetime(2026, 10, 27, 12)


class GrantReaderTests(unittest.TestCase):
    def setUp(self):
        self.grants = [self.grant()]
        self.lesson = self.row()
        self.course = "course-a"
        db = types.SimpleNamespace(get_value=self.get_value, get_all=self.get_all)
        frappe = types.ModuleType("frappe")
        frappe.db = db
        utils = types.ModuleType("frappe.utils")
        utils.get_datetime = lambda value: value if isinstance(value, datetime) else datetime.fromisoformat(value)
        utils.now_datetime = lambda: NOW
        self.modules = patch.dict(sys.modules, {"frappe": frappe, "frappe.utils": utils})
        self.modules.start()
        self.addCleanup(self.modules.stop)
        spec = importlib.util.spec_from_file_location("test_individual_access", ROOT / "lms/lms/individual_access.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        self.check = lambda user="student-a", lesson="lesson-a": module.grant_allows_lesson(
            user=user, lesson=lesson, now=NOW)

    @staticmethod
    def grant(**changes):
        value = dict(name="grant-a", member="student-a", course="course-a", status="Active",
                     starts_at=NOW - timedelta(days=1), personal_end_type="Unlimited", ends_at=None,
                     course_end_type="Unlimited", course_ends_at=None, ignore_course_end=0)
        value.update(changes)
        return types.SimpleNamespace(**value)

    @staticmethod
    def row(**changes):
        value = dict(opens_at=NOW, prerequisite_state="Clear", manual_open=0)
        value.update(changes)
        return types.SimpleNamespace(**value)

    def get_value(self, doctype, key, field, **kwargs):
        if doctype == "Course Lesson":
            return self.course if key == "lesson-a" else None
        if doctype == "LMS Access Grant Lesson":
            return self.lesson if key["parent"] == "grant-a" and key["lesson"] == "lesson-a" else None
        raise AssertionError(doctype)

    def get_all(self, doctype, filters, fields):
        self.assertEqual(doctype, "LMS Access Grant")
        return [g for g in self.grants if all(getattr(g, key) == value for key, value in filters.items())]

    def test_matching_student_course_and_lesson_are_all_required(self):
        self.assertTrue(self.check())
        self.assertFalse(self.check(user="student-b"))
        self.assertFalse(self.check(lesson="lesson-b"))
        self.assertFalse(self.check(user="Guest"))
        self.course = "other"
        self.assertFalse(self.check())

    def test_revoked_frozen_and_incomplete_grants_do_not_open(self):
        for changes in ({"status": "Frozen"}, {"status": "Revoked"}, {"starts_at": None},
                        {"starts_at": NOW + timedelta(seconds=1)}, {"personal_end_type": "Unknown"},
                        {"course_end_type": "Unknown"}, {"ignore_course_end": None}):
            with self.subTest(changes=changes):
                self.grants = [self.grant(**changes)]
                self.assertFalse(self.check())

    def test_fixed_deadlines_and_ignore_course_end(self):
        self.grants = [self.grant(personal_end_type="At", ends_at=NOW)]
        self.assertFalse(self.check())
        self.grants = [self.grant(course_end_type="At", course_ends_at=NOW)]
        self.assertFalse(self.check())
        self.grants = [self.grant(course_end_type="At", course_ends_at=NOW, ignore_course_end=1)]
        self.assertTrue(self.check())

    def test_schedule_and_manual_override_only_apply_to_assigned_lesson(self):
        self.lesson = self.row(opens_at=NOW + timedelta(days=1), prerequisite_state="Blocked")
        self.assertFalse(self.check())
        self.lesson.manual_open = 1
        self.assertTrue(self.check())
        self.assertFalse(self.check(user="student-b"))
        self.grants = [self.grant(status="Frozen")]
        self.assertFalse(self.check())
        self.grants = [self.grant()]
        self.lesson = None
        self.assertFalse(self.check())

    def test_any_valid_grant_is_sufficient(self):
        self.grants = [self.grant(personal_end_type="Unknown"), self.grant()]
        self.assertTrue(self.check())


if __name__ == "__main__":
    unittest.main()

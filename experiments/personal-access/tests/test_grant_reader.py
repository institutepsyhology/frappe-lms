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
        self.default_rule = None
        self.course = "course-a"
        db = types.SimpleNamespace(get_value=self.get_value, get_all=self.get_all)
        frappe = types.ModuleType("frappe")
        frappe.db = db
        frappe.conf = {}
        self.frappe = frappe
        utils = types.ModuleType("frappe.utils")
        utils.get_datetime = lambda value: value if isinstance(value, datetime) else datetime.fromisoformat(value)
        utils.now_datetime = lambda: NOW
        self.modules = patch.dict(sys.modules, {"frappe": frappe, "frappe.utils": utils})
        self.modules.start()
        self.addCleanup(self.modules.stop)
        spec = importlib.util.spec_from_file_location("test_individual_access", ROOT / "lms/lms/individual_access.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        self.module = module
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
        value = dict(opening_type="At", opens_at=NOW, delay_days=0, prerequisite_state="Clear", manual_open=0,
                     retain_when_limited=0, retention_end_type="Unknown", retention_ends_at=None)
        value.update(changes)
        return types.SimpleNamespace(**value)

    def get_value(self, doctype, key, field, **kwargs):
        if doctype == "Course Lesson":
            return self.course if key == "lesson-a" else None
        if doctype == "LMS Access Grant Lesson":
            return self.lesson if key["parent"] == "grant-a" and key["lesson"] == "lesson-a" else None
        if doctype == "LMS Access Policy":
            return "policy-a" if self.default_rule else None
        if doctype == "LMS Access Policy Lesson":
            return self.default_rule if key["parent"] == "policy-a" and key["lesson"] == "lesson-a" else None
        raise AssertionError(doctype)

    def get_all(self, doctype, filters, fields):
        self.assertEqual(doctype, "LMS Access Grant")
        return [g for g in self.grants if all(
            getattr(g, key) in value[1] if isinstance(value, tuple) and value[0] == "in"
            else getattr(g, key) == value for key, value in filters.items())]

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

    def test_release_barrier_leaves_existing_course_behavior_unchanged(self):
        self.assertFalse(self.module.policy_applies("course-a"))
        self.grants = []
        self.assertTrue(self.module.restrict_member_lesson(
            course="course-a", lesson="lesson-a", user="student-a", enrolled=True))
        self.assertFalse(self.module.restrict_member_lesson(
            course="course-a", lesson="lesson-a", user="student-a", enrolled=False))

    def test_only_explicit_server_switch_reads_per_course_policy(self):
        self.frappe.conf["individual_access_release_enabled"] = "true"
        self.assertFalse(self.module.policy_applies("course-a"))
        self.frappe.conf["individual_access_release_enabled"] = True
        self.frappe.db.get_all = lambda doctype, **kwargs: ["course-a"] if doctype == "LMS Access Policy" else []
        self.assertTrue(self.module.policy_applies("course-a"))
        self.assertFalse(self.module.policy_applies("course-b"))

    def test_policy_when_simulated_narrows_membership_and_never_creates_it(self):
        with patch.object(self.module, "policy_applies", return_value=True):
            self.assertTrue(self.module.restrict_member_lesson(
                course="course-a", lesson="lesson-a", user="student-a", enrolled=True))
            self.assertFalse(self.module.restrict_member_lesson(
                course="course-a", lesson="lesson-a", user="student-b", enrolled=True))
            self.assertFalse(self.module.restrict_member_lesson(
                course="course-a", lesson="lesson-a", user="student-a", enrolled=False))

    def test_outline_masks_closed_lesson_media_and_keeps_open_lesson(self):
        first = types.SimpleNamespace(name="lesson-a", youtube="video-a", quiz_id="quiz-a", question="q-a")
        second = types.SimpleNamespace(name="lesson-b", youtube="video-b", quiz_id="quiz-b", question="q-b")
        outline = [types.SimpleNamespace(lessons=[first, second])]
        self.module.mask_inaccessible_outline(outline, lambda lesson: lesson == "lesson-a")
        self.assertEqual(first.youtube, "video-a")
        self.assertEqual(first.quiz_id, "quiz-a")
        self.assertEqual(second.locked, 1)
        self.assertIsNone(second.youtube)
        self.assertIsNone(second.quiz_id)
        self.assertIsNone(second.question)

    def test_assignment_reference_must_be_exact_and_in_assignment_block(self):
        blocks = [{"type": "assignment", "data": {"assignment": "assignment-a"}},
                  {"type": "text", "data": {"assignment": "assignment-b"}},
                  {"type": "assignment", "data": None}]
        self.assertTrue(self.module.assignment_in_lesson("assignment-a", blocks))
        self.assertFalse(self.module.assignment_in_lesson("assignment-b", blocks))
        self.assertFalse(self.module.assignment_in_lesson("assignment", blocks))

    def test_course_schedule_uses_each_student_start_and_allows_personal_override(self):
        self.default_rule = self.row(opening_type="After Start", opens_at=None, delay_days=2)
        self.lesson = self.row(opening_type="Inherit", opens_at=None)
        self.grants = [self.grant(starts_at=NOW - timedelta(days=1))]
        self.assertFalse(self.check())
        self.grants = [self.grant(starts_at=NOW - timedelta(days=2))]
        self.assertTrue(self.check())
        self.lesson = self.row(opening_type="After Start", opens_at=None, delay_days=3)
        self.assertFalse(self.check())
        self.lesson.manual_open = 1
        self.assertTrue(self.check())

    def test_missing_default_schedule_remains_closed(self):
        self.lesson = self.row(opening_type="Inherit", opens_at=None)
        self.assertFalse(self.check())

    def test_closed_course_keeps_only_explicit_lessons_for_the_selected_student(self):
        self.grants = [self.grant(status="Limited", ends_at=NOW, personal_end_type="At")]
        self.assertFalse(self.check())
        self.lesson = self.row(retain_when_limited=1, retention_end_type="Unlimited")
        self.assertTrue(self.check())
        self.assertFalse(self.check(user="student-b"))
        self.lesson.retention_end_type = "At"
        self.lesson.retention_ends_at = NOW
        self.assertFalse(self.check())


if __name__ == "__main__":
    unittest.main()

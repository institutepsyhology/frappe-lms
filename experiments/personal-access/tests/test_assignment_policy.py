"""Assignment permission checks with a fake Frappe database."""

import importlib.util
import json
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[3]


class AssignmentPolicyTests(unittest.TestCase):
    def setUp(self):
        self.courses = ("protected",)
        self.lesson_rows = []
        self.allowed = set()
        self.author_courses = set()
        self.assignment_courses = {"task": None}
        frappe = types.ModuleType("frappe")
        frappe._ = lambda value: value
        frappe.session = types.SimpleNamespace(user="student")
        frappe.db = types.SimpleNamespace(get_all=self.get_all, get_value=self.get_value)
        qb = types.ModuleType("frappe.query_builder")
        qb.Bracket = lambda x: x
        pypika = types.ModuleType("pypika")
        terms = types.ModuleType("pypika.terms")
        terms.LiteralValue = lambda x: x
        utils = types.ModuleType("lms.lms.utils")
        for name in ("can_modify_batch", "can_modify_course", "get_membership", "guest_access_allowed", "has_moderator_role"):
            setattr(utils, name, lambda *args, **kwargs: False)
        utils.get_editorjs_blocks = lambda value: json.loads(value or "{}").get("blocks", [])
        access = types.ModuleType("lms.lms.individual_access")
        access.protected_courses = lambda: self.courses
        access.policy_applies = lambda course: course in self.courses
        access.assignment_in_lesson = lambda name, blocks: any(
            b.get("type") == "assignment" and (b.get("data") or {}).get("assignment") == name for b in blocks)
        lesson_controller = types.ModuleType("lms.lms.doctype.course_lesson.course_lesson")
        lesson_controller._resolve_lesson_references = lambda url: [(row.name, False) for row in self.lesson_rows]
        lesson_controller._references_vouched_by_owner = lambda references, owner: references
        self.modules = patch.dict(sys.modules, {"frappe": frappe, "frappe.query_builder": qb,
                                               "pypika": pypika, "pypika.terms": terms,
                                               "lms.lms.utils": utils, "lms.lms.individual_access": access,
                                               "lms.lms.doctype.course_lesson.course_lesson": lesson_controller})
        self.modules.start()
        self.addCleanup(self.modules.stop)
        spec = importlib.util.spec_from_file_location("test_permissions", ROOT / "lms/lms/permissions.py")
        self.permissions = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.permissions)
        self.permissions.can_author_course = lambda course, user=None: course in self.author_courses
        self.permissions.can_access_lesson = lambda lesson, instructor_only=False, user=None: lesson in self.allowed
        self.permissions.has_authored_content_permission = lambda doc, ptype, user: True

    def get_all(self, doctype, **kwargs):
        self.assertEqual(doctype, "Course Lesson")
        return self.lesson_rows

    def get_value(self, doctype, name, field):
        if doctype == "LMS Assignment":
            return self.assignment_courses.get(name)
        if doctype == "Course Lesson":
            return next((row.course for row in self.lesson_rows if row.name == name), None)
        raise AssertionError(doctype)

    def doc(self, name="task"):
        return types.SimpleNamespace(name=name, is_new=lambda: False, get=lambda field: self.assignment_courses.get(name))

    @staticmethod
    def lesson(name, assignment):
        content = json.dumps({"blocks": [{"type": "assignment", "data": {"assignment": assignment}}]})
        return types.SimpleNamespace(name=name, course="protected", content=content)

    def test_course_less_assignment_is_protected_when_placed_in_a_protected_lesson(self):
        self.lesson_rows = [self.lesson("lesson-a", "task")]
        self.assertFalse(self.permissions.assignment_has_permission(self.doc(), user="student"))
        self.allowed.add("lesson-a")
        self.assertTrue(self.permissions.assignment_has_permission(self.doc(), user="student"))
        self.assertFalse(self.permissions.assignment_has_permission(self.doc(), ptype="write", user="student"))

    def test_author_and_unrelated_assignment_preserve_authorized_access(self):
        self.lesson_rows = [self.lesson("lesson-a", "task")]
        self.assertTrue(self.permissions.assignment_has_permission(self.doc("unrelated"), user="student"))
        self.author_courses.add("protected")
        self.assertTrue(self.permissions.assignment_has_permission(self.doc(), ptype="write", user="teacher"))

    def test_missing_placement_for_protected_course_is_denied(self):
        self.assignment_courses["task"] = "protected"
        self.assertFalse(self.permissions.assignment_has_permission(self.doc(), user="student"))

    def test_no_protected_courses_keeps_existing_permission_behavior(self):
        self.courses = ()
        self.assignment_courses["task"] = "protected"
        self.assertTrue(self.permissions.assignment_has_permission(self.doc(), user="student"))

    def test_existing_content_author_restriction_is_preserved(self):
        self.permissions.has_authored_content_permission = lambda doc, ptype, user: False
        self.assertFalse(self.permissions.assignment_has_permission(self.doc(), ptype="write", user="student"))

    def test_direct_private_file_is_denied_until_referencing_lesson_is_open(self):
        self.lesson_rows = [self.lesson("lesson-a", "task")]
        values = {"is_private": 1, "file_url": "/private/files/example", "owner": "teacher",
                  "attached_to_doctype": "Other", "attached_to_field": None}
        file_doc = types.SimpleNamespace(**values, get=lambda key: values.get(key))
        self.assertFalse(self.permissions.file_has_permission(file_doc, user="student"))
        self.allowed.add("lesson-a")
        self.permissions.can_access_lesson = lambda lesson, instructor_only=False, user=None: lesson in self.allowed
        self.assertTrue(self.permissions.file_has_permission(file_doc, user="student"))


if __name__ == "__main__":
    unittest.main()

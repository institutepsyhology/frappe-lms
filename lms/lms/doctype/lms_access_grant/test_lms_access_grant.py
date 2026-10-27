"""Integration tests intended for an isolated Frappe site only."""

import json
from unittest.mock import patch

import frappe
from frappe.utils import add_to_date, now_datetime

from lms.lms.doctype.course_lesson import course_lesson
from lms.lms.permissions import can_access_lesson
from lms.lms.test_helpers import BaseTestUtils


class TestIndividualAccessIntegration(BaseTestUtils):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.teacher = cls._create_user("stage-teacher@example.invalid", "Test", "Teacher", ["Course Creator"])
		cls.student = cls._create_user("stage-student@example.invalid", "Test", "Student", ["LMS Student"])
		cls.other = cls._create_user("stage-other@example.invalid", "Test", "Other", ["LMS Student"])
		cls.course = cls._create_course(title="Isolated individual access test", instructor=cls.teacher.email)
		cls.chapter = cls._create_chapter("Isolated test chapter", cls.course.name)
		cls._create_chapter_reference(cls.course.name, cls.chapter.name)
		cls.lesson = cls._create_lesson("Isolated test lesson", cls.chapter.name, cls.course.name)
		cls._create_lesson_reference(cls.chapter.name, cls.lesson.name)
		cls._create_enrollment(cls.student.email, cls.course.name)
		cls._create_enrollment(cls.other.email, cls.course.name)
		cls.grant = frappe.get_doc({
			"doctype": "LMS Access Grant", "member": cls.student.email, "course": cls.course.name,
			"status": "Active", "starts_at": add_to_date(now_datetime(), days=-1),
			"personal_end_type": "Unlimited", "course_end_type": "Unlimited",
			"lessons": [{"lesson": cls.lesson.name, "opens_at": add_to_date(now_datetime(), days=-1),
				"prerequisite_state": "Clear"}],
		}).insert(ignore_permissions=True)

	def setUp(self):
		super().setUp()
		self.policy = patch("lms.lms.individual_access.protected_courses", return_value=(self.course.name,))
		self.policy.start()
		self.addCleanup(self.policy.stop)

	def tearDown(self):
		frappe.set_user("Administrator")
		super().tearDown()

	def test_student_with_grant_and_student_without_grant(self):
		frappe.set_user(self.student.email)
		self.assertTrue(can_access_lesson(self.lesson.name))
		frappe.set_user(self.other.email)
		self.assertFalse(can_access_lesson(self.lesson.name))
		self.assertFalse(frappe.has_permission("Course Lesson", "read", self.lesson.name))
		# The stock LMS Student role has no direct Course Lesson list permission.
		with self.assertRaises(frappe.PermissionError):
			frappe.get_list("Course Lesson", pluck="name")
		condition = course_lesson.get_permission_query_conditions(self.other.email)
		names = frappe.db.sql("select name from `tabCourse Lesson` where " + condition, pluck=True)
		self.assertNotIn(self.lesson.name, names)
		with self.assertRaises(frappe.PermissionError):
			course_lesson._save_progress(self.lesson.name, self.course.name)

	def test_personal_early_open_and_frozen_access(self):
		frappe.db.set_value("LMS Access Grant Lesson", self.grant.lessons[0].name,
			{"opens_at": add_to_date(now_datetime(), days=2), "manual_open": 1})
		frappe.set_user(self.student.email)
		self.assertTrue(can_access_lesson(self.lesson.name))
		frappe.set_user("Administrator")
		frappe.db.set_value("LMS Access Grant", self.grant.name, "status", "Frozen")
		frappe.set_user(self.student.email)
		self.assertFalse(can_access_lesson(self.lesson.name))

	def test_assignment_without_course_follows_actual_lesson(self):
		assignment = frappe.get_doc({"doctype": "LMS Assignment", "title": "Isolated task",
			"type": "Text", "question": "Test question"}).insert(ignore_permissions=True)
		content = json.dumps({"blocks": [{"type": "assignment", "data": {"assignment": assignment.name}}]})
		frappe.db.set_value("Course Lesson", self.lesson.name, "content", content)
		frappe.set_user(self.other.email)
		self.assertFalse(frappe.has_permission("LMS Assignment", "read", assignment.name))
		frappe.set_user(self.student.email)
		self.assertTrue(frappe.has_permission("LMS Assignment", "read", assignment.name))

"""Integration tests intended for an isolated Frappe site only."""

import json
from unittest.mock import patch

import frappe
from frappe.utils import add_to_date, now_datetime
from frappe.utils.file_manager import save_file

from lms.lms.doctype.course_lesson import course_lesson
from lms.lms.permissions import can_access_lesson, file_has_permission
from lms.lms.test_helpers import BaseTestUtils
from lms.lms.utils import get_course_outline, get_lesson


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
			"lessons": [{"lesson": cls.lesson.name, "opening_type": "At", "opens_at": add_to_date(now_datetime(), days=-1),
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

	def test_lesson_and_outline_hide_content_from_other_student(self):
		frappe.db.set_value("Course Lesson", self.lesson.name, "youtube", "https://example.invalid/test-video")
		frappe.set_user(self.other.email)
		self.assertTrue(get_lesson(self.course.name, 1, 1).get("no_preview"))
		outline = get_course_outline(self.course.name, progress=True)
		row = outline[0].lessons[0]
		self.assertEqual(row.locked, 1)
		self.assertIsNone(row.youtube)
		frappe.set_user(self.student.email)
		self.assertFalse(get_lesson(self.course.name, 1, 1).get("no_preview"))

	def test_private_file_is_gated_by_its_real_lesson(self):
		frappe.set_user(self.teacher.email)
		file_doc = save_file("stage-example.txt", b"test", "Course Lesson", self.lesson.name, is_private=1)
		file_doc.db_set("attached_to_field", "content")
		frappe.set_user(self.other.email)
		self.assertFalse(file_has_permission(file_doc))
		with self.assertRaises(frappe.PermissionError):
			course_lesson.serve_resource(file_doc.file_url)
		frappe.set_user(self.student.email)
		self.assertTrue(file_has_permission(file_doc))
		with patch.object(course_lesson, "_serve_private_file", return_value="allowed"):
			self.assertEqual(course_lesson.serve_resource(file_doc.file_url), "allowed")

	def test_explicit_course_opt_in_requires_server_release_switch(self):
		self.policy.stop()
		from lms.lms.individual_access import protected_courses

		frappe.get_doc({"doctype": "LMS Access Policy", "course": self.course.name, "enabled": 1}).insert(
			ignore_permissions=True
		)
		with patch.dict(frappe.conf, {"individual_access_release_enabled": False}):
			self.assertNotIn(self.course.name, protected_courses())
		with patch.dict(frappe.conf, {"individual_access_release_enabled": True}):
			self.assertIn(self.course.name, protected_courses())

	def test_inherited_schedule_counts_from_personal_start_and_allows_override(self):
		frappe.get_doc({"doctype": "LMS Access Policy", "course": self.course.name, "enabled": 1,
			"lessons": [{"lesson": self.lesson.name, "opening_type": "After Start", "delay_days": 2}]}).insert(
			ignore_permissions=True
		)
		frappe.db.set_value("LMS Access Grant Lesson", self.grant.lessons[0].name,
			{"opening_type": "Inherit", "opens_at": None, "delay_days": 0})
		frappe.db.set_value("LMS Access Grant", self.grant.name, "starts_at", add_to_date(now_datetime(), days=-1))
		frappe.set_user(self.student.email)
		self.assertFalse(can_access_lesson(self.lesson.name))
		frappe.set_user("Administrator")
		frappe.db.set_value("LMS Access Grant", self.grant.name, "starts_at", add_to_date(now_datetime(), days=-3))
		frappe.set_user(self.student.email)
		self.assertTrue(can_access_lesson(self.lesson.name))
		frappe.set_user("Administrator")
		frappe.db.set_value("LMS Access Grant Lesson", self.grant.lessons[0].name,
			{"opening_type": "After Start", "delay_days": 5})
		frappe.set_user(self.student.email)
		self.assertFalse(can_access_lesson(self.lesson.name))

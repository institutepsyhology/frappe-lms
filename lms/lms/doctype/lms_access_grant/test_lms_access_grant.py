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

	def test_course_access_overview_is_limited_to_administrator(self):
		from lms.lms.access_actions import get_course_access_overview

		result = get_course_access_overview(self.course.name)
		self.assertIn(self.grant.name, [grant.name for grant in result["grants"]])
		self.assertIn(self.lesson.name, [lesson.name for lesson in result["lessons"]])
		self.assertFalse(result["policy_exists"])
		frappe.set_user(self.student.email)
		with self.assertRaises(frappe.PermissionError):
			get_course_access_overview(self.course.name)

	def test_create_course_policy_stays_disabled_and_rejects_duplicates(self):
		from lms.lms.access_actions import create_course_access_policy

		frappe.set_user(self.student.email)
		with self.assertRaises(frappe.PermissionError):
			create_course_access_policy(self.course.name)
		frappe.set_user("Administrator")
		result = create_course_access_policy(self.course.name)
		policy = frappe.get_doc("LMS Access Policy", result["name"])
		self.assertFalse(policy.enabled)
		self.assertEqual(policy.default_personal_end_type, "Unknown")
		self.assertEqual(policy.lessons[0].lesson, self.lesson.name)
		self.assertEqual(policy.lessons[0].opening_type, "Unknown")
		with self.assertRaises(frappe.ValidationError):
			create_course_access_policy(self.course.name)

	def test_course_defaults_require_admin_and_remain_disabled(self):
		from lms.lms.access_actions import create_course_access_policy, update_course_access_defaults

		policy_name = create_course_access_policy(self.course.name)["name"]
		values = {"default_personal_end_type": "After Start", "default_personal_end_at": None,
			"default_personal_end_days": 30, "global_end_type": "Unlimited", "global_end_at": None,
			"completed_retention_type": "Days", "completed_retention_days": 14}
		frappe.set_user(self.student.email)
		with self.assertRaises(frappe.PermissionError):
			update_course_access_defaults(self.course.name, values)
		frappe.set_user("Administrator")
		update_course_access_defaults(self.course.name, values)
		policy = frappe.get_doc("LMS Access Policy", policy_name)
		self.assertEqual(policy.default_personal_end_days, 30)
		self.assertEqual(policy.completed_retention_days, 14)
		self.assertFalse(policy.enabled)
		values["default_personal_end_days"] = 0
		with self.assertRaises(frappe.ValidationError):
			update_course_access_defaults(self.course.name, values)

	def test_lesson_rule_is_validated_without_enabling_policy(self):
		from lms.lms.access_actions import create_course_access_policy, update_course_lesson_rule

		name = create_course_access_policy(self.course.name)["name"]
		rule = {"opening_type": "After Start", "opens_at": None, "delay_days": 3,
			"prerequisite_type": "None", "prerequisite_lesson": None, "prerequisite_assignment": None}
		frappe.set_user(self.other.email)
		with self.assertRaises(frappe.PermissionError):
			update_course_lesson_rule(self.course.name, self.lesson.name, rule)
		frappe.set_user("Administrator")
		update_course_lesson_rule(self.course.name, self.lesson.name, rule)
		policy = frappe.get_doc("LMS Access Policy", name)
		self.assertFalse(policy.enabled)
		self.assertEqual(policy.lessons[0].delay_days, 3)
		with self.assertRaises(frappe.ValidationError):
			update_course_lesson_rule(self.course.name, "unknown-lesson", rule)

	def test_admin_creates_inherited_grant_for_enrolled_student(self):
		from lms.lms.access_actions import create_grant_for_enrolled_student

		frappe.get_doc({"doctype": "LMS Access Policy", "course": self.course.name}).insert(ignore_permissions=True)
		start = now_datetime().replace(microsecond=0)
		result = create_grant_for_enrolled_student(self.course.name, self.other.email, start.isoformat(),
			json.dumps([self.lesson.name]))
		grant = frappe.get_doc("LMS Access Grant", result["name"])
		self.assertEqual((grant.member, grant.status, grant.personal_end_type), (self.other.email, "Active", "Inherit"))
		self.assertEqual(grant.starts_at, start)
		self.assertEqual((grant.lessons[0].lesson, grant.lessons[0].opening_type), (self.lesson.name, "Inherit"))
		with self.assertRaises(frappe.ValidationError):
			create_grant_for_enrolled_student(self.course.name, self.other.email, str(start), [self.lesson.name])
		frappe.db.set_value("LMS Access Grant", grant.name, "status", "Revoked")
		reissued = create_grant_for_enrolled_student(self.course.name, self.other.email, str(start), [self.lesson.name])
		self.assertNotEqual(reissued["name"], grant.name)
		self.assertEqual(frappe.db.get_value("LMS Access Grant", grant.name, "status"), "Revoked")

	def test_create_grant_rejects_unauthorized_and_unenrolled(self):
		from lms.lms.access_actions import create_grant_for_enrolled_student

		start = str(now_datetime())
		frappe.set_user(self.other.email)
		with self.assertRaises(frappe.PermissionError):
			create_grant_for_enrolled_student(self.course.name, self.other.email, start, [self.lesson.name])
		frappe.set_user("Administrator")
		with self.assertRaises(frappe.ValidationError):
			create_grant_for_enrolled_student(self.course.name, self.teacher.email, start, [self.lesson.name])

	def test_personal_early_open_and_frozen_access(self):
		frappe.db.set_value("LMS Access Grant Lesson", self.grant.lessons[0].name,
			{"opens_at": add_to_date(now_datetime(), days=2), "manual_open": 1})
		frappe.set_user(self.student.email)
		self.assertTrue(can_access_lesson(self.lesson.name))
		frappe.set_user("Administrator")
		frappe.db.set_value("LMS Access Grant", self.grant.name, "status", "Frozen")
		frappe.set_user(self.student.email)
		self.assertFalse(can_access_lesson(self.lesson.name))

	def test_admin_can_open_only_an_assigned_lesson_early(self):
		from lms.lms.access_actions import get_grant_lessons, set_grant_lesson_manual_open

		frappe.db.set_value("LMS Access Grant Lesson", self.grant.lessons[0].name,
			{"opens_at": add_to_date(now_datetime(), days=2), "manual_open": 0})
		frappe.set_user(self.other.email)
		with self.assertRaises(frappe.PermissionError):
			get_grant_lessons(self.grant.name)
		frappe.set_user("Administrator")
		self.assertEqual(get_grant_lessons(self.grant.name)[0]["lesson"], self.lesson.name)
		with self.assertRaises(frappe.ValidationError):
			set_grant_lesson_manual_open(self.grant.name, "unknown-lesson", 1)
		set_grant_lesson_manual_open(self.grant.name, self.lesson.name, 1)
		frappe.set_user(self.student.email)
		self.assertTrue(can_access_lesson(self.lesson.name))
		frappe.set_user("Administrator")
		set_grant_lesson_manual_open(self.grant.name, self.lesson.name, 0)
		frappe.set_user(self.student.email)
		self.assertFalse(can_access_lesson(self.lesson.name))

	def test_admin_changes_assigned_lessons_without_removing_progress(self):
		from lms.lms.access_actions import set_grant_assigned_lessons

		second = self._create_lesson("Another assigned lesson", self.chapter.name, self.course.name)
		progress = self._create_progress(self.student.email, self.course.name, self.lesson.name)
		frappe.set_user(self.other.email)
		with self.assertRaises(frappe.PermissionError):
			set_grant_assigned_lessons(self.grant.name, [second.name])
		frappe.set_user("Administrator")
		with self.assertRaises(frappe.ValidationError):
			set_grant_assigned_lessons(self.grant.name, ["unknown-lesson"])
		set_grant_assigned_lessons(self.grant.name, [self.lesson.name, second.name])
		grant = frappe.get_doc("LMS Access Grant", self.grant.name)
		self.assertEqual(grant.lessons[0].opening_type, "At")
		self.assertEqual(grant.lessons[1].opening_type, "Inherit")
		set_grant_assigned_lessons(self.grant.name, [second.name])
		self.assertTrue(frappe.db.exists("LMS Course Progress", progress.name))
		self.assertEqual([row.lesson for row in frappe.get_doc("LMS Access Grant", self.grant.name).lessons], [second.name])

	def test_revoke_closes_access_and_preserves_progress_and_enrollment(self):
		from lms.lms.access_actions import revoke_grant

		progress = self._create_progress(self.student.email, self.course.name, self.lesson.name)
		assignment = frappe.get_doc({"doctype": "LMS Assignment", "title": "Preserved homework",
			"type": "Text", "question": "Test question"}).insert(ignore_permissions=True)
		frappe.db.set_value("Course Lesson", self.lesson.name, "content",
			json.dumps({"blocks": [{"type": "assignment", "data": {"assignment": assignment.name}}]}))
		submission = frappe.get_doc({"doctype": "LMS Assignment Submission", "assignment": assignment.name,
			"lesson": self.lesson.name, "member": self.student.email, "type": "Text", "answer": "Test answer"})
		submission.insert(ignore_permissions=True)
		frappe.set_user(self.other.email)
		with self.assertRaises(frappe.PermissionError):
			revoke_grant(self.grant.name)
		frappe.set_user("Administrator")
		self.assertEqual(revoke_grant(self.grant.name)["status"], "Revoked")
		self.assertTrue(frappe.db.exists("LMS Course Progress", progress.name))
		self.assertTrue(frappe.db.exists("LMS Assignment Submission", submission.name))
		self.assertTrue(frappe.db.exists("LMS Enrollment", {"member": self.student.email, "course": self.course.name}))
		frappe.set_user(self.student.email)
		self.assertFalse(can_access_lesson(self.lesson.name))

	def test_admin_can_change_only_one_students_start_and_personal_end(self):
		from lms.lms.access_actions import update_grant_timing

		progress = self._create_progress(self.student.email, self.course.name, self.lesson.name)
		start = add_to_date(now_datetime(), days=-2).replace(microsecond=0)
		args = (self.grant.name, start.isoformat(), "After Start", None, 30, 1)
		frappe.set_user(self.other.email)
		with self.assertRaises(frappe.PermissionError):
			update_grant_timing(*args)
		frappe.set_user("Administrator")
		update_grant_timing(*args)
		grant = frappe.get_doc("LMS Access Grant", self.grant.name)
		self.assertEqual(grant.starts_at, start)
		self.assertEqual((grant.personal_end_type, grant.personal_end_days, grant.ignore_course_end), ("After Start", 30, 1))
		self.assertTrue(frappe.db.exists("LMS Course Progress", progress.name))
		with self.assertRaises(frappe.ValidationError):
			update_grant_timing(self.grant.name, start.isoformat(), "After Start", None, 0, 1)

	def test_assignment_without_course_follows_actual_lesson(self):
		assignment = frappe.get_doc({"doctype": "LMS Assignment", "title": "Isolated task",
			"type": "Text", "question": "Test question"}).insert(ignore_permissions=True)
		content = json.dumps({"blocks": [{"type": "assignment", "data": {"assignment": assignment.name}}]})
		frappe.db.set_value("Course Lesson", self.lesson.name, "content", content)
		frappe.set_user(self.other.email)
		self.assertFalse(frappe.has_permission("LMS Assignment", "read", assignment.name))
		frappe.set_user(self.student.email)
		self.assertTrue(frappe.has_permission("LMS Assignment", "read", assignment.name))

	def test_admin_lists_only_assignments_placed_in_selected_lesson(self):
		from lms.lms.access_actions import get_lesson_assignments

		assignment = frappe.get_doc({"doctype": "LMS Assignment", "title": "Lesson homework",
			"type": "Text", "question": "Test question"}).insert(ignore_permissions=True)
		frappe.db.set_value("Course Lesson", self.lesson.name, "content",
			json.dumps({"blocks": [{"type": "assignment", "data": {"assignment": assignment.name}}]}))
		self.assertEqual([item.name for item in get_lesson_assignments(self.course.name, self.lesson.name)], [assignment.name])
		frappe.set_user(self.student.email)
		with self.assertRaises(frappe.PermissionError):
			get_lesson_assignments(self.course.name, self.lesson.name)

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

	def test_scorm_lesson_checks_personal_access_before_redirect(self):
		frappe.db.set_value("Course Lesson", self.lesson.name, "is_scorm_package", 1)
		frappe.set_user(self.other.email)
		blocked = get_lesson(self.course.name, 1, 1)
		self.assertTrue(blocked.get("no_preview"))
		self.assertFalse(blocked.get("is_scorm_package"))
		frappe.set_user(self.student.email)
		self.assertTrue(get_lesson(self.course.name, 1, 1).get("is_scorm_package"))

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

	def test_freeze_resume_requires_admin_and_preserves_course_end(self):
		from lms.lms.access_actions import freeze_grant, resume_grant

		frappe.set_user(self.other.email)
		with self.assertRaises(frappe.PermissionError):
			freeze_grant(self.grant.name)
		frappe.set_user("Administrator")
		end = add_to_date(now_datetime(), days=10)
		frappe.db.set_value("LMS Access Grant", self.grant.name, {"personal_end_type": "At", "ends_at": end})
		freeze_grant(self.grant.name)
		frappe.db.set_value("LMS Access Grant", self.grant.name, "frozen_at", add_to_date(now_datetime(), days=-2))
		with self.assertRaises(frappe.ValidationError):
			resume_grant(self.grant.name, "unknown")
		resume_grant(self.grant.name, 1)
		grant = frappe.get_doc("LMS Access Grant", self.grant.name)
		self.assertEqual(grant.status, "Active")
		self.assertGreater(grant.ends_at, add_to_date(end, days=1))
		self.assertEqual(grant.course_end_type, "Unlimited")

	def test_limiting_access_retains_only_selected_lessons_and_preserves_progress(self):
		from lms.lms.access_actions import limit_grant

		progress = self._create_progress(self.student.email, self.course.name, self.lesson.name)
		limit_grant(self.grant.name, [self.lesson.name], "Unlimited")
		self.assertTrue(frappe.db.exists("LMS Course Progress", progress.name))
		frappe.set_user(self.student.email)
		self.assertTrue(can_access_lesson(self.lesson.name))
		frappe.set_user(self.other.email)
		self.assertFalse(can_access_lesson(self.lesson.name))

	def test_limiting_access_rejects_unassigned_lesson_without_changing_grant(self):
		from lms.lms.access_actions import limit_grant

		with self.assertRaises(frappe.ValidationError):
			limit_grant(self.grant.name, ["unknown-lesson"], "Unlimited")
		self.assertEqual(frappe.db.get_value("LMS Access Grant", self.grant.name, "status"), "Active")

	def test_inherited_duration_and_personal_course_end_exception(self):
		frappe.get_doc({"doctype": "LMS Access Policy", "course": self.course.name, "enabled": 1,
			"default_personal_end_type": "After Start", "default_personal_end_days": 2,
			"global_end_type": "At", "global_end_at": add_to_date(now_datetime(), days=-1)}).insert(
			ignore_permissions=True
		)
		frappe.db.set_value("LMS Access Grant", self.grant.name,
			{"personal_end_type": "Inherit", "course_end_type": "Inherit", "ignore_course_end": 0})
		frappe.set_user(self.student.email)
		self.assertFalse(can_access_lesson(self.lesson.name))
		frappe.set_user("Administrator")
		frappe.db.set_value("LMS Access Grant", self.grant.name, "ignore_course_end", 1)
		frappe.set_user(self.student.email)
		self.assertTrue(can_access_lesson(self.lesson.name))

	def test_resume_extends_inherited_duration_without_moving_course_end(self):
		from lms.lms.access_actions import freeze_grant, resume_grant

		frappe.get_doc({"doctype": "LMS Access Policy", "course": self.course.name, "enabled": 1,
			"default_personal_end_type": "After Start", "default_personal_end_days": 5}).insert(ignore_permissions=True)
		frappe.db.set_value("LMS Access Grant", self.grant.name, "personal_end_type", "Inherit")
		freeze_grant(self.grant.name)
		frappe.db.set_value("LMS Access Grant", self.grant.name, "frozen_at", add_to_date(now_datetime(), days=-2))
		resume_grant(self.grant.name, 1)
		grant = frappe.get_doc("LMS Access Grant", self.grant.name)
		self.assertEqual(grant.personal_end_type, "At")
		self.assertGreater(grant.ends_at, add_to_date(now_datetime(), days=5))
		self.assertEqual(grant.course_end_type, "Unlimited")

	def test_completed_lesson_retention_requires_actual_progress_and_known_expiry(self):
		frappe.get_doc({"doctype": "LMS Access Policy", "course": self.course.name, "enabled": 1,
			"completed_retention_type": "Days", "completed_retention_days": 2}).insert(ignore_permissions=True)
		frappe.db.set_value("LMS Access Grant", self.grant.name,
			{"personal_end_type": "At", "ends_at": add_to_date(now_datetime(), days=-1)})
		frappe.set_user(self.student.email)
		self.assertFalse(can_access_lesson(self.lesson.name))
		frappe.set_user("Administrator")
		progress = self._create_progress(self.student.email, self.course.name, self.lesson.name)
		frappe.db.set_value("LMS Course Progress", progress.name, "status", "Complete")
		frappe.set_user(self.student.email)
		self.assertTrue(can_access_lesson(self.lesson.name))
		frappe.set_user("Administrator")
		frappe.db.set_value("LMS Access Grant", self.grant.name, {"personal_end_type": "Unknown", "ends_at": None})
		frappe.set_user(self.student.email)
		self.assertFalse(can_access_lesson(self.lesson.name))

	def test_quiz_direct_read_requires_access_to_its_protected_lesson(self):
		quiz = frappe.get_doc({"doctype": "LMS Quiz", "title": "Isolated quiz"}).insert(ignore_permissions=True)
		content = json.dumps({"blocks": [{"type": "quiz", "data": {"quiz": quiz.name}}]})
		frappe.db.set_value("Course Lesson", self.lesson.name, "content", content)
		frappe.set_user(self.other.email)
		self.assertFalse(frappe.has_permission("LMS Quiz", "read", quiz.name))
		self.assertFalse(frappe.has_permission("LMS Quiz", "export", quiz.name))
		self.assertNotIn(quiz.name, frappe.get_list("LMS Quiz", pluck="name"))
		frappe.set_user(self.student.email)
		self.assertTrue(frappe.has_permission("LMS Quiz", "read", quiz.name))
		self.assertFalse(frappe.has_permission("LMS Quiz", "share", quiz.name))

	def test_manual_override_bypasses_sequence_only_for_the_selected_student(self):
		second = self._create_lesson("Second isolated lesson", self.chapter.name, self.course.name)
		frappe.get_doc({"doctype": "Lesson Reference", "lesson": second.name, "parent": self.chapter.name,
			"parenttype": "Course Chapter", "parentfield": "lessons", "idx": 2}).insert(ignore_permissions=True)
		frappe.db.set_value("LMS Course", self.course.name, "enforce_lesson_completion", 1)
		grant = frappe.get_doc("LMS Access Grant", self.grant.name)
		grant.append("lessons", {"lesson": second.name, "opening_type": "Unknown", "manual_open": 1})
		grant.save(ignore_permissions=True)
		frappe.set_user(self.student.email)
		payload = get_lesson(self.course.name, 1, 2)
		self.assertFalse(payload.get("locked"))
		self.assertFalse(payload.get("no_preview"))
		frappe.set_user(self.other.email)
		self.assertFalse(can_access_lesson(second.name))

	def test_next_lesson_waits_for_this_students_assignment_approval(self):
		second = self._create_lesson("Assignment gated lesson", self.chapter.name, self.course.name)
		assignment = frappe.get_doc({"doctype": "LMS Assignment", "title": "Required assignment",
			"type": "Text", "question": "Test question"}).insert(ignore_permissions=True)
		content = json.dumps({"blocks": [{"type": "assignment", "data": {"assignment": assignment.name}}]})
		frappe.db.set_value("Course Lesson", self.lesson.name, "content", content)
		frappe.get_doc({"doctype": "LMS Access Policy", "course": self.course.name, "enabled": 1,
			"lessons": [{"lesson": second.name, "opening_type": "After Start", "delay_days": 0,
				"prerequisite_type": "Assignment Passed", "prerequisite_lesson": self.lesson.name,
				"prerequisite_assignment": assignment.name}]}).insert(ignore_permissions=True)
		grant = frappe.get_doc("LMS Access Grant", self.grant.name)
		grant.append("lessons", {"lesson": second.name, "opening_type": "Inherit", "prerequisite_state": "Inherit"})
		grant.save(ignore_permissions=True)
		frappe.set_user(self.student.email)
		self.assertFalse(can_access_lesson(second.name))
		frappe.set_user("Administrator")
		submission = frappe.get_doc({"doctype": "LMS Assignment Submission", "assignment": assignment.name,
			"lesson": self.lesson.name, "member": self.student.email, "type": "Text", "answer": "Test answer"})
		submission.insert(ignore_permissions=True)
		frappe.set_user(self.student.email)
		self.assertFalse(can_access_lesson(second.name))
		frappe.set_user("Administrator")
		frappe.db.set_value("LMS Assignment Submission", submission.name, "status", "Pass")
		frappe.set_user(self.student.email)
		self.assertTrue(can_access_lesson(second.name))
		frappe.set_user(self.other.email)
		self.assertFalse(can_access_lesson(second.name))

	def test_legacy_prerequisite_value_remains_accessible_and_normalizes_on_save(self):
		frappe.db.set_value("LMS Access Grant Lesson", self.grant.lessons[0].name, "prerequisite_state", "Clear")
		frappe.set_user(self.student.email)
		self.assertTrue(can_access_lesson(self.lesson.name))
		frappe.set_user("Administrator")
		grant = frappe.get_doc("LMS Access Grant", self.grant.name)
		grant.save(ignore_permissions=True)
		self.assertEqual(grant.lessons[0].prerequisite_state, "Satisfied")

	def test_explicitly_retained_lesson_bypasses_sequence_after_closure(self):
		from lms.lms.access_actions import limit_grant

		second = self._create_lesson("Retained isolated lesson", self.chapter.name, self.course.name)
		frappe.get_doc({"doctype": "Lesson Reference", "lesson": second.name, "parent": self.chapter.name,
			"parenttype": "Course Chapter", "parentfield": "lessons", "idx": 2}).insert(ignore_permissions=True)
		frappe.db.set_value("LMS Course", self.course.name, "enforce_lesson_completion", 1)
		grant = frappe.get_doc("LMS Access Grant", self.grant.name)
		grant.append("lessons", {"lesson": second.name, "opening_type": "At",
			"opens_at": add_to_date(now_datetime(), days=2), "prerequisite_state": "Blocked"})
		grant.save(ignore_permissions=True)
		limit_grant(self.grant.name, [second.name], "Unlimited")
		frappe.set_user(self.student.email)
		payload = get_lesson(self.course.name, 1, 2)
		self.assertFalse(payload.get("locked"))
		self.assertFalse(payload.get("no_preview"))
		frappe.set_user(self.other.email)
		self.assertFalse(can_access_lesson(second.name))

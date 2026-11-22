import json
from unittest.mock import patch

import frappe

from lms.lms.doctype.course_lesson import course_lesson
from lms.lms.permissions import get_locked_lessons
from lms.lms.test_helpers import BaseTestUtils


class TestOptionalAssignmentProgress(BaseTestUtils):
	def setUp(self):
		super().setUp()
		self.teacher = self._create_user("optional.teacher@example.com", "Teacher", "Test", ["Course Creator"])
		self.student = self._create_user("optional.student@example.com", "Learner", "Test", ["LMS Student"])
		self.course = self._create_course("Optional written exercise", instructor=self.teacher.email)
		self.chapter = self._create_chapter("Optional exercises", self.course.name)
		self._create_chapter_reference(self.course.name, self.chapter.name)
		self.lesson = self._create_lesson("First unit", self.chapter.name, self.course.name)
		self.next_lesson = self._create_lesson("Second unit", self.chapter.name, self.course.name)
		self._create_lesson_reference(self.chapter.name, self.lesson.name)
		frappe.get_doc({"doctype":"Lesson Reference", "lesson":self.next_lesson.name, "parent":self.chapter.name,
			"parenttype":"Course Chapter", "parentfield":"lessons", "idx":2}).insert()
		self._create_enrollment(self.student.name, self.course.name)
		self.optional = self._create_assignment("Optional exercise")
		self.required = self._create_assignment("Required exercise")
		frappe.db.set_value("LMS Assignment", self.optional.name, "avo_optional", 1)
		frappe.db.set_value("LMS Course", self.course.name, "enforce_lesson_completion", 1)
		frappe.db.set_single_value("LMS Settings", "enforce_assignment_completion", 1)
		frappe.db.set_single_value("LMS Settings", "enforce_quiz_completion", 1)
		self.enterContext(patch.object(course_lesson, "capture"))

	def tearDown(self):
		frappe.set_user("Administrator")
		super().tearDown()

	def exercise(self, *, legacy=False, required=False, quiz=False):
		items = [("assignment", self.optional.name)]
		if required:
			items.append(("assignment", self.required.name))
		if quiz:
			exam = self._create_quiz(self._create_quiz_questions(), title="Still required quiz")
			items.append(("quiz", exam.name))
		if legacy:
			lesson = {"content":None, "body":"\n".join('{{ '+kind.title()+'("'+name+'") }}' for kind,name in items)}
		else:
			lesson = {"content":json.dumps({"blocks":[{"type":kind,"data":{kind:name}} for kind,name in items]})}
		frappe.db.set_value("Course Lesson", self.lesson.name, lesson)
		frappe.set_user(self.student.name)
		self.assertIn(self.next_lesson.name, get_locked_lessons(self.course.name))
		course_lesson.save_progress(self.lesson.name, self.course.name)
		filters = {"lesson":self.lesson.name, "member":self.student.name, "status":"Complete"}
		return bool(frappe.db.exists("LMS Course Progress", filters))

	def test_optional_editor_block_completes_without_submission_and_unlocks_next(self):
		self.assertTrue(self.exercise())
		self.assertNotIn(self.next_lesson.name, get_locked_lessons(self.course.name))
		self.assertFalse(frappe.db.exists("LMS Assignment Submission", {"member":self.student.name}))

	def test_optional_legacy_macro_completes_without_submission(self):
		self.assertTrue(self.exercise(legacy=True))
		self.assertNotIn(self.next_lesson.name, get_locked_lessons(self.course.name))

	def test_mandatory_assignment_in_same_lesson_still_requires_answer(self):
		self.assertFalse(self.exercise(required=True))
		self.assertIn(self.next_lesson.name, get_locked_lessons(self.course.name))

	def test_quiz_in_same_lesson_still_requires_result(self):
		self.assertFalse(self.exercise(quiz=True))
		self.assertIn(self.next_lesson.name, get_locked_lessons(self.course.name))

	def test_old_schema_treats_assignment_as_required(self):
		original = frappe.db.has_column
		def old_schema(dt, field, *args, **kwargs):
			if dt == "LMS Assignment" and field == "avo_optional":
				return False
			return original(dt, field, *args, **kwargs)
		with patch.object(frappe.db, "has_column", side_effect=old_schema):
			self.assertFalse(self.exercise())

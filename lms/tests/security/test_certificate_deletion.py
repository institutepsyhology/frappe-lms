"""Check certificate assignments using only in-memory course and batch records."""

import inspect
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import frappe

from lms.lms import utils
from lms.lms.doctype.lms_certificate import lms_certificate as certificates


class CertificatePermissionTests(unittest.TestCase):
	def setUp(self):
		self.member = "learner@example.test"
		self.evaluator = "reviewer@example.test"
		self.other = "colleague@example.test"
		self.roles = {self.evaluator: ["Batch Evaluator"], self.other: ["Batch Evaluator"]}
		self.saved = frappe._dict(
			name="certificate-1", course="course-one", batch_name="morning",
			member=self.member, evaluator=None,
		)
		self.card = frappe._dict(self.saved, owner="office@example.test", published=0)
		self.batch_courses = {"morning": self.evaluator, "evening": self.other}
		self.enrollments = {("morning", self.member)}
		self.progress = 100
		self.new_certificate = Mock()
		self.framework = SimpleNamespace(
			session=SimpleNamespace(user=self.member),
			get_roles=lambda user: self.roles.get(user, ["LMS Student"]),
			db=SimpleNamespace(get_value=self.get_value, exists=self.exists),
			get_all=Mock(return_value=[]), get_doc=Mock(return_value=self.new_certificate),
			throw=Mock(side_effect=ValueError),
		)
		for module in (certificates, utils):
			self.enterContext(patch.object(module, "frappe", self.framework))
		self.enterContext(patch.object(certificates, "_", str))

	def get_value(self, doctype, key, fields, **kwargs):
		if doctype == "LMS Certificate":
			return self.saved if key == self.saved.name else None
		if doctype == "Batch Course":
			return self.batch_courses.get(key["parent"]) if key["course"] == "course-one" else None
		if doctype == "LMS Course" and key == "course-one":
			return {"evaluator": self.other, "enable_certification": 1}[fields]
		if doctype == "LMS Enrollment" and fields == "progress":
			self.assertEqual(key, {"course": "course-one", "member": self.member})
			return self.progress
		self.fail(f"Unexpected lookup for {doctype}")

	def exists(self, doctype, filters):
		if doctype == "Batch Course":
			return (
				filters["parenttype"] == "LMS Batch"
				and self.batch_courses.get(filters["parent"]) == filters["evaluator"]
			)
		if doctype == "LMS Batch Enrollment":
			return (filters["batch"], filters["member"]) in self.enrollments
		if doctype == "LMS Enrollment":
			return filters == {"course": "course-one", "member": self.member}
		self.fail(f"Unexpected enrollment lookup for {doctype}")

	def may_delete(self, user):
		return certificates.has_permission(self.card, ptype="delete", user=user)

	def test_assigned_batch_evaluator_and_other_batch_evaluator(self):
		self.assertTrue(self.may_delete(self.evaluator))
		self.assertFalse(self.may_delete(self.other))

	def test_batch_only_certificate_needs_assignment_and_enrollment(self):
		self.saved.course = None
		self.assertTrue(self.may_delete(self.evaluator))
		self.assertFalse(self.may_delete(self.other))
		self.enrollments.clear()
		self.assertFalse(self.may_delete(self.evaluator))

	def test_course_only_certificate_uses_course_evaluator(self):
		self.saved.batch_name = None
		self.assertTrue(self.may_delete(self.other))
		self.assertFalse(self.may_delete(self.evaluator))

	def test_explicit_assignment_uses_saved_certificate(self):
		self.saved.update({"course": None, "batch_name": None, "evaluator": self.other})
		self.card.update({"evaluator": self.evaluator, "owner": self.evaluator})
		self.assertTrue(self.may_delete(self.other))
		self.assertFalse(self.may_delete(self.evaluator))
		self.card.name = "new-certificate"
		self.assertFalse(self.may_delete(self.other))

	def test_broader_roles_come_from_account(self):
		self.card.roles = ["Moderator"]
		self.assertFalse(self.may_delete(self.other))
		for role in ("Moderator", "Course Creator", "System Manager"):
			with self.subTest(role=role):
				self.roles[self.other] = ["Batch Evaluator", role]
				self.assertTrue(self.may_delete(self.other))
		self.roles[self.other] = ["LMS Student"]
		self.assertFalse(self.may_delete(self.other))

	def test_existing_read_and_print_rules(self):
		self.assertTrue(certificates.has_permission(self.card, ptype="read", user=self.other))
		self.assertFalse(certificates.has_permission(self.card, ptype="read", user=self.member))
		self.card.published = 1
		for action in ("read", "select", "print"):
			self.assertTrue(certificates.has_permission(self.card, ptype=action, user=self.member))
		self.assertFalse(self.may_delete(self.member))

	def test_eligible_student_can_still_receive_own_certificate(self):
		issue = inspect.unwrap(certificates.create_certificate)
		with patch.object(certificates, "nowdate", return_value="2026-01-01"), patch.object(
			certificates, "get_default_certificate_template", return_value="Sample"
		):
			self.progress = 80
			with self.assertRaises(ValueError):
				issue("course-one")
			self.framework.get_doc.assert_not_called()
			self.progress = 100
			self.assertIs(issue("course-one"), self.new_certificate)
		self.framework.get_doc.assert_called_once_with(
			{
				"doctype": "LMS Certificate", "member": self.member, "course": "course-one",
				"issue_date": "2026-01-01", "template": "Sample",
			}
		)
		self.new_certificate.save.assert_called_once()

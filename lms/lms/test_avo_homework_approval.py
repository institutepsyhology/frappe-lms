from datetime import datetime, timedelta
from unittest.mock import patch

import frappe

from lms.lms import avo_homework_approval as approval
from lms.lms.test_helpers import BaseTestUtils


class TestAutomaticWrittenReview(BaseTestUtils):
	def setUp(self):
		super().setUp()
		self.assignment = self._create_assignment("Timed written review")
		self.learner = self._create_user("automatic.grade@example.com", "Learner", "Test", ["LMS Student"])
		self.filters = {"assignment": self.assignment.name, "member": self.learner.name}
		self.at = datetime(2026, 1, 10, 12)
		self.clock = self.enterContext(patch.object(approval, "now_datetime", return_value=self.at))
		self.enterContext(patch("lms.lms.doctype.lms_assignment_submission.lms_assignment_submission.make_notification_logs"))

	def tearDown(self):
		frappe.set_user("Administrator")
		super().tearDown()

	def submit(self, hours):
		self.assignment.avo_auto_approve = 1
		self.assignment.avo_auto_approve_hours = hours
		self.assignment.save()
		frappe.set_user(self.learner.name)
		return frappe.get_doc({"doctype": approval.SUBMISSION, **self.filters, "answer": "First answer",
			"avo_answer_submitted_at": self.at - timedelta(days=5)}).insert()

	def test_immediate_and_empty_answers(self):
		doc = self.submit(0)
		self.assertEqual(doc.status, "Pass")
		self.assertTrue(approval.assignment_passed(self.filters))
		doc.answer = "<p>&nbsp;</p>"
		with self.assertRaises(frappe.ValidationError):
			doc.save()

	def test_exact_deadline_and_scheduler(self):
		doc = self.submit(24)
		frappe.set_user("Administrator")
		self.clock.return_value += timedelta(hours=24) - timedelta(seconds=1)
		self.assertFalse(approval.assignment_passed(self.filters))
		approval.approve_due()
		self.assertEqual(doc.reload().status, approval.PENDING)
		self.clock.return_value += timedelta(seconds=1)
		self.assertTrue(approval.assignment_passed(self.filters))
		for _ in range(2):
			approval.approve_due()
			self.assertEqual(doc.reload().status, "Pass")

	def test_rejection_and_revised_answer(self):
		doc = self.submit(24)
		frappe.set_user("Administrator")
		doc.status = "Fail"
		doc.save()
		self.clock.return_value += timedelta(days=2)
		approval.approve_due()
		self.assertFalse(approval.assignment_passed(self.filters))
		self.assertEqual(doc.reload().status, "Fail")
		frappe.set_user(self.learner.name)
		doc.save()
		self.assertEqual(doc.status, "Fail")
		doc.answer = "Revised answer"
		doc.save()
		self.assertEqual(doc.status, approval.PENDING)
		self.assertFalse(approval.assignment_passed(self.filters))
		self.clock.return_value += timedelta(hours=24)
		self.assertTrue(approval.assignment_passed(self.filters))

	def test_no_synthetic_attempt_and_early_manual_pass(self):
		doc = self.submit(24)
		frappe.set_user("Administrator")
		frappe.db.set_value(approval.SUBMISSION, doc.name, approval.ATTEMPT_TIME, None)
		doc.reload()
		self.clock.return_value += timedelta(days=90)
		approval.approve_due()
		self.assertFalse(approval.assignment_passed(self.filters))
		doc.status = "Pass"
		doc.save()
		self.assertTrue(approval.assignment_passed(self.filters))

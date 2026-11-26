"""Exercise issuance through ordinary staff flows using synthetic group assignments."""

import inspect
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import frappe

from lms.lms import api, utils
from lms.lms.doctype.lms_certificate import lms_certificate as certificates
from lms.lms.doctype.lms_certificate_evaluation import lms_certificate_evaluation as evaluations


class BatchIssuanceTests(unittest.TestCase):
	def setUp(self):
		self.reviewer = "reviewer@example.test"
		self.member = "learner@example.test"
		self.assignments = {"morning": self.reviewer, "evening": "colleague@example.test", None: None}
		self.enrollments = {("morning", self.member), ("evening", self.member)}
		self.rows = {
			(doctype, batch): frappe._dict(
				name=f"{doctype}-{batch}", course="sample", batch_name=batch,
				member=self.member, evaluator=self.assignments[batch], published=0,
			)
			for doctype in ("LMS Certificate", "LMS Certificate Evaluation") for batch in ("morning", "evening")
		}
		self.locks = []
		self.roles = ["Batch Evaluator"]
		self.framework = SimpleNamespace(
			session=SimpleNamespace(user=self.reviewer), PermissionError=PermissionError,
			only_for=Mock(), get_roles=lambda user: self.roles,
			throw=lambda message, error=ValueError: self.fail_with(error, message),
			db=SimpleNamespace(get_value=self.get_value, set_value=self.set_value, exists=self.exists),
			new_doc=Mock(),
		)
		for module in (api, utils, certificates, evaluations):
			self.enterContext(patch.object(module, "frappe", self.framework))
		for module in (api, certificates, evaluations):
			self.enterContext(patch.object(module, "_", str))
		self.enterContext(patch.object(api, "has_moderator_role", return_value=False))
		self.enterContext(patch.object(evaluations, "is_evaluation_admin", return_value=False))

	@staticmethod
	def fail_with(error, message):
		raise error(message)

	def get_value(self, doctype, key, fields, **kwargs):
		if doctype == "Batch Course":
			return self.assignments[key["parent"]] if key["course"] == "sample" else None
		if doctype == "LMS Course":
			return None
		if kwargs.get("for_update"):
			self.locks.append(doctype)
		if doctype == "User":
			self.assertEqual((key, fields), (self.member, "name"))
			return self.member
		if isinstance(key, dict):
			self.assertEqual(key["member"], self.member)
			self.assertEqual(key["course"], "sample")
			if isinstance(key["batch_name"], list):
				self.assertEqual(key["batch_name"], ["is", "not set"])
				return None
			return self.rows[doctype, key["batch_name"]].name
		return next((row for (typ, _), row in self.rows.items() if typ == doctype and row.name == key), None)

	def set_value(self, doctype, name, fields):
		row = self.get_value(doctype, name, None)
		self.assertIsNotNone(row)
		row.update(fields)

	def exists(self, doctype, key):
		self.assertEqual(doctype, "LMS Batch Enrollment")
		return (key["batch"], key["member"]) in self.enrollments

	def test_new_and_moved_records_require_enrollment_in_the_evaluators_group(self):
		other_member = "another-learner@example.test"
		self.enrollments.add(("evening", other_member))
		for module, doctype in ((certificates, "LMS Certificate"), (evaluations, "LMS Certificate Evaluation")):
			with self.subTest(document=doctype):
				card = frappe._dict(self.rows[doctype, "morning"], member=other_member)
				self.assertFalse(module.has_permission(card, "create"))
				self.assertFalse(module.has_permission(card, "write"))
				self.enrollments.add(("morning", other_member))
				self.assertTrue(module.has_permission(card, "create"))
				self.assertTrue(module.has_permission(card, "write"))
				self.enrollments.remove(("morning", other_member))

	def test_both_save_forms_require_membership_before_issuing_a_record(self):
		self.enrollments.remove(("morning", self.member))
		with self.assertRaises(PermissionError):
			inspect.unwrap(api.save_certificate_details)(self.member, "2026-01-10", "Template", "sample", "morning")
		with self.assertRaises(PermissionError):
			inspect.unwrap(api.save_evaluation_details)(self.member, "sample", "2026-01-10", "09:00", "09:30", "Pass", "morning", 5)
		self.assertEqual(self.locks, [])
		self.framework.new_doc.assert_not_called()

	def test_create_and_write_require_own_assignment(self):
		for batch in ("morning", "evening"):
			card = self.rows["LMS Certificate", batch]
			for action in ("create", "write", "delete"):
				with self.subTest(batch=batch, action=action):
					self.assertEqual(certificates.has_permission(card, action), batch == "morning")
			self.assertTrue(certificates.has_permission(card, "read"))
		for role in ("System Manager", "Moderator", "Course Creator"):
			self.roles = ["Batch Evaluator", role]
			self.assertTrue(certificates.has_permission(self.rows["LMS Certificate", "evening"], "write"))

	def test_updating_certificate_and_evaluation_selects_the_current_batch(self):
		other_cert = self.rows["LMS Certificate", "evening"].copy()
		other_eval = self.rows["LMS Certificate Evaluation", "evening"].copy()
		issue = inspect.unwrap(api.save_certificate_details)
		evaluate = inspect.unwrap(api.save_evaluation_details)
		cert_name = issue(self.member, "2026-01-10", "Template", "sample", "morning")
		eval_name = evaluate(self.member, "sample", "2026-01-10", "09:00", "09:30", "Pass", "morning", 5)
		self.assertEqual(cert_name, self.rows["LMS Certificate", "morning"].name)
		self.assertEqual(eval_name, self.rows["LMS Certificate Evaluation", "morning"].name)
		self.assertEqual(self.rows["LMS Certificate", "morning"].issue_date, "2026-01-10")
		self.assertEqual(self.rows["LMS Certificate Evaluation", "morning"].status, "Pass")
		self.assertEqual(self.rows["LMS Certificate", "evening"], other_cert)
		self.assertEqual(self.rows["LMS Certificate Evaluation", "evening"], other_eval)
		self.assertEqual(self.locks, ["User", "LMS Certificate", "User", "LMS Certificate Evaluation"])
		self.assertIsNone(api._evaluation_record("LMS Certificate", self.member, "sample", None))

	def test_new_certificate_in_a_second_batch_is_created_separately(self):
		self.rows.pop(("LMS Certificate", "morning"))
		old_get = self.framework.db.get_value
		def absent(doctype, key, fields, **kwargs):
			if doctype == "LMS Certificate" and isinstance(key, dict) and key.get("batch_name") == "morning":
				return None
			return old_get(doctype, key, fields, **kwargs)
		self.framework.db.get_value = absent
		inspect.unwrap(api.save_certificate_details)(self.member, "2026-01-10", "Template", "sample", "morning")
		self.framework.new_doc.assert_called_once_with("LMS Certificate")
		new = self.framework.new_doc.return_value
		self.assertEqual(new.update.call_args.args[0]["batch_name"], "morning")
		new.insert.assert_called_once_with()
		self.assertIsNone(self.rows["LMS Certificate", "evening"].issue_date)

	def test_evaluation_authorizes_own_saved_batch(self):
		for batch in ("morning", "evening"):
			with self.subTest(batch=batch):
				card = self.rows["LMS Certificate Evaluation", batch]
				self.assertEqual(evaluations.has_permission(card, "write"), batch == "morning")

	def test_current_group_assignment_and_enrollment_control_existing_records(self):
		for remove_what in ("assignment", "enrollment"):
			if remove_what == "assignment":
				self.assignments["morning"] = "successor@example.test"
			else:
				self.assignments["morning"] = self.reviewer
				self.enrollments.discard(("morning", self.member))
			for module, doctype in ((certificates, "LMS Certificate"), (evaluations, "LMS Certificate Evaluation")):
				card = self.rows[doctype, "morning"]
				for action in ("write", "delete"):
					with self.subTest(remove=remove_what, doctype=doctype, action=action):
						self.assertFalse(module.has_permission(card, action))
			with self.assertRaises(PermissionError):
				inspect.unwrap(evaluations.create_lms_certificate)(self.rows["LMS Certificate Evaluation", "morning"].name)

	def test_mapping_a_normal_evaluation_initializes_a_typed_certificate(self):
		card = self.rows["LMS Certificate Evaluation", "morning"]
		target = Mock()
		self.framework.new_doc.return_value = target
		with patch.object(evaluations, "get_mapped_doc", return_value=target) as mapper:
			result = inspect.unwrap(evaluations.create_lms_certificate)(card.name)
		self.assertIs(result, target)
		self.assertIs(mapper.call_args.args[3], target)
		target.update.assert_called_once_with(
			{field: card[field] for field in ("member", "course", "batch_name", "evaluator")}
		)

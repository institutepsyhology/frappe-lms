# Copyright (c) 2022, Frappe and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.model.mapper import get_mapped_doc
from frappe.query_builder import Bracket
from pypika.terms import LiteralValue

from lms.lms.utils import get_evaluator, has_moderator_role, is_member_of_batch


class LMSCertificateEvaluation(Document):
	def validate(self):
		self.validate_rating()

	def validate_rating(self):
		if self.status not in ["Pending", "In Progress"] and self.rating == 0:
			frappe.throw(_("Rating cannot be 0"))


def has_website_permission(doc, ptype, user, verbose=False):
	if has_moderator_role() or doc.member == frappe.session.user:
		return True
	return False


def is_evaluation_admin(user=None):
	user = user or frappe.session.user
	return bool(has_moderator_role(user)) or "System Manager" in frappe.get_roles(user)


def has_permission(doc, ptype="read", user=None):
	"""The Batch Evaluator DocPerm grants CRUD on the whole doctype, so without
	this every evaluator could grade, retitle or delete any other evaluator's
	evaluations over the generic REST path. Returning False is what denies them.

	`has_website_permission` above only covers portal routes; the desk, reports,
	Data Import and /api/resource never consult it.
	"""
	user = user or frappe.session.user
	if is_evaluation_admin(user):
		return True

	if ptype in ("read", "select", "print"):
		return doc.evaluator == user or doc.member == user

	if ptype == "create":
		# The caller picks `evaluator` on a new row, so trusting that field alone
		# would let any evaluator mint a Pass for any member on any course. Ask the
		# same question save_evaluation_details asks: who is assigned to this
		# course/batch? Members never create their own evaluation -- they book an
		# LMS Certificate Request that an evaluator or Moderator converts.
		return doc.evaluator == user and _can_grade_member(doc, user)

	if ptype in ("write", "delete"):
		stored = frappe.db.get_value(
			"LMS Certificate Evaluation", doc.name, ["evaluator", "course", "batch_name", "member"], as_dict=True
		) if doc.name else None
		if not stored or stored.evaluator != user or (stored.batch_name and not _can_grade_member(stored, user)):
			return False
		if ptype == "delete":
			return True
		if doc.evaluator != user:
			return False
		if (doc.course, doc.batch_name, doc.member) == (stored.course, stored.batch_name, stored.member):
			return True
		return _can_grade_member(doc, user)

	return False


def _can_grade_member(doc, user):
	return get_evaluator(doc.course, doc.batch_name) == user and (
		not doc.batch_name or is_member_of_batch(doc.member, doc.batch_name)
	)


def get_permission_query_conditions(user=None):
	"""List-read counterpart of has_permission above: a hook is consulted on
	single-document reads but not on list queries, and this is the reverse, so
	registering one without the other leaves half the doctype open."""
	user = user or frappe.session.user
	if user == "Administrator":
		return ""

	if is_evaluation_admin(user):
		return ""

	evaluation = frappe.qb.DocType("LMS Certificate Evaluation")
	# LiteralValue around frappe.db.escape, not the bare string: pypika inlines a value
	# by doubling quotes alone, which leaves a backslash live on MariaDB. Bracket keeps
	# the OR together once the caller ANDs this onto the rest of the where clause.
	member = LiteralValue(frappe.db.escape(user))
	condition = Bracket((evaluation.evaluator == member) | (evaluation.member == member))
	return condition.get_sql(with_namespace=True, quote_char="`" if frappe.db.db_type == "mariadb" else '"')


@frappe.whitelist()
def create_lms_certificate(source_name: str, target_doc: dict = None):
	# The type hint alone only raises under frappe.flags.in_test; in production
	# typing_validations logs and lets the value through.
	if not isinstance(source_name, str):
		frappe.throw(_("Evaluation must be a string."))

	evaluation = frappe.db.get_value(
		"LMS Certificate Evaluation", source_name, ["evaluator", "course", "batch_name", "member"], as_dict=True
	)
	if not evaluation or (not is_evaluation_admin() and (
		evaluation.evaluator != frappe.session.user
		or (evaluation.batch_name and not _can_grade_member(evaluation, frappe.session.user))
	)):
		frappe.throw(
			_("You are not the assigned evaluator for this evaluation."),
			frappe.PermissionError,
		)

	# Framework checks creation permission on the target before it maps the source.
	if target_doc:
		if isinstance(target_doc, str):
			target_doc = frappe.parse_json(target_doc)
		if isinstance(target_doc, dict):
			target_doc = frappe.get_doc(target_doc)
		if not isinstance(target_doc, Document) or target_doc.doctype != "LMS Certificate" or not target_doc.is_new():
			frappe.throw(_("Expected a new certificate."))
	else:
		target_doc = frappe.new_doc("LMS Certificate")
	target_doc.update({field: evaluation.get(field) for field in ("member", "course", "batch_name", "evaluator")})
	doc = get_mapped_doc(
		"LMS Certificate Evaluation",
		source_name,
		{"LMS Certificate Evaluation": {"doctype": "LMS Certificate"}},
		target_doc,
	)
	return doc

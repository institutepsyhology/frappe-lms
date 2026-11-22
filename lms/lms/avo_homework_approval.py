"""Apply a written assignment's automatic review interval to a real learner response."""

from datetime import timedelta
from html import unescape

import frappe
from frappe import _
from frappe.utils import now_datetime, strip_html_tags

ASSIGNMENT = "LMS Assignment"
SUBMISSION = "LMS Assignment Submission"
ATTEMPT_TIME = "avo_answer_submitted_at"
PENDING = "Not Graded"


def schema_ready():
	return (frappe.db.has_column(ASSIGNMENT, "avo_auto_approve")
		and frappe.db.has_column(ASSIGNMENT, "avo_auto_approve_hours")
		and frappe.db.has_column(SUBMISSION, ATTEMPT_TIME))


def approval_hours(assignment):
	if not assignment or not schema_ready():
		return None
	settings = frappe.db.get_value(ASSIGNMENT, assignment,
		["type", "avo_auto_approve", "avo_auto_approve_hours"], as_dict=True)
	if not settings or settings.type != "Text" or not settings.avo_auto_approve:
		return None
	hours = settings.avo_auto_approve_hours
	return hours if type(hours) is int and 0 <= hours <= 99999 else None


def prepare_attempt(doc):
	"""Run after ownership, grading-permission and rich-text validation."""
	previous = doc.get_doc_before_save()
	# This clock is server-owned. Never infer an attempt from creation/modified.
	doc.set(ATTEMPT_TIME, previous.get(ATTEMPT_TIME) if previous else None)
	hours = approval_hours(doc.assignment)
	identity_changed = previous and (doc.assignment, doc.member) != (previous.assignment, previous.member)
	if identity_changed and (hours is not None or previous.get(ATTEMPT_TIME) or approval_hours(previous.assignment) is not None):
		frappe.throw(_("The assignment and learner of this response cannot be changed."))
	if hours is None:
		doc.set(ATTEMPT_TIME, None)
		return
	if doc.member != frappe.session.user:
		# A staff decision, including manually returning a grade to pending, wins.
		# Staff edits cannot serve as evidence of a new learner submission.
		if not previous or doc.status != previous.status or doc.answer != previous.answer:
			doc.set(ATTEMPT_TIME, None)
		return
	if previous and doc.answer == previous.answer:
		if doc.status != previous.status:
			doc.set(ATTEMPT_TIME, None)
		return
	answer = unescape(strip_html_tags(doc.answer or "")).replace("\u200b", "").replace("\ufeff", "").strip()
	if not answer:
		frappe.throw(_("Please provide a written answer before submitting."))
	doc.set(ATTEMPT_TIME, now_datetime())
	doc.status = "Pass" if hours == 0 else PENDING


def assignment_passed(filters):
	if frappe.db.exists(SUBMISSION, {**filters, "status": "Pass"}):
		return True
	hours = approval_hours(filters["assignment"])
	if hours is None:
		return False
	# Make the gate accurate even between scheduler ticks, without writing on a read.
	return bool(frappe.db.exists(SUBMISSION, {**filters, "status": PENDING,
		ATTEMPT_TIME: ["<=", now_datetime() - timedelta(hours=hours)]}))


def approve_due():
	"""Update due answers without a fabricated evaluator, comment or instructor email."""
	if not schema_ready():
		return
	assignment = frappe.qb.DocType(ASSIGNMENT)
	submission = frappe.qb.DocType(SUBMISSION)
	now = now_datetime()
	enabled = (assignment.type == "Text") & (assignment.avo_auto_approve == 1)
	intervals = (frappe.qb.from_(assignment).select(assignment.avo_auto_approve_hours)
		.distinct().where(enabled).run(pluck=True))
	for hours in intervals:
		if type(hours) is not int or not 0 <= hours <= 99999:
			continue
		matching = (frappe.qb.from_(assignment).select(assignment.name)
			.where(enabled & (assignment.avo_auto_approve_hours == hours)))
		# Check the current grade and attempt timestamp in the same write. A
		# concurrent rejection or resubmission invalidates the former deadline.
		(frappe.qb.update(submission).set(submission.status, "Pass")
			.set(submission.modified, now).set(submission.modified_by, frappe.session.user)
			.where((submission.status == PENDING) & submission.assignment.isin(matching)
				& (submission.avo_answer_submitted_at <= now - timedelta(hours=hours))).run())

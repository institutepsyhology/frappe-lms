"""Explicit administrator actions for personal access grants."""

import frappe
from frappe import _
from frappe.utils import get_datetime, now_datetime


def _admin_grant(name):
	frappe.only_for("System Manager")
	if not isinstance(name, str) or not name:
		frappe.throw(_("A grant name is required."), frappe.ValidationError)
	grant = frappe.get_doc("LMS Access Grant", name, for_update=True)
	grant.check_permission("write")
	return grant


def _explicit_choice(value):
	if value is True or value == "1" or type(value) is int and value == 1:
		return True
	if value is False or value == "0" or type(value) is int and value == 0:
		return False
	frappe.throw(_("Choose explicitly whether to extend the personal end date."), frappe.ValidationError)


@frappe.whitelist(methods=["POST"])
def freeze_grant(name):
	"""Freeze one active grant without changing homework, progress or dates."""
	grant = _admin_grant(name)
	if grant.status != "Active":
		frappe.throw(_("Only an active grant can be frozen."), frappe.ValidationError)
	grant.frozen_at = now_datetime()
	grant.status = "Frozen"
	grant.save()
	return {"name": grant.name, "status": grant.status}


@frappe.whitelist(methods=["POST"])
def resume_grant(name, extend_personal_end):
	"""Resume one frozen grant, optionally extending only its finite personal end.

	The course end and the start/schedule do not move. Other AWO freeze variants
	remain unimplemented; this action never deletes homework or progress.
	"""
	extend = _explicit_choice(extend_personal_end)
	grant = _admin_grant(name)
	if grant.status != "Frozen" or not grant.frozen_at:
		frappe.throw(_("Only a frozen grant with a known freeze time can be resumed."), frappe.ValidationError)
	now = now_datetime()
	elapsed = now - get_datetime(grant.frozen_at)
	if elapsed.total_seconds() < 0:
		frappe.throw(_("The freeze time is in the future."), frappe.ValidationError)
	if extend and grant.personal_end_type == "Unknown":
		frappe.throw(_("The personal end is unknown and cannot be extended."), frappe.ValidationError)
	if extend and grant.personal_end_type == "At":
		if not grant.ends_at:
			frappe.throw(_("The personal end date is missing."), frappe.ValidationError)
		grant.ends_at = get_datetime(grant.ends_at) + elapsed
	grant.status = "Active"
	grant.frozen_at = None
	grant.save()
	return {"name": grant.name, "status": grant.status, "personal_end": grant.ends_at}

"""Explicit administrator actions for personal access grants."""

import frappe
from frappe import _
from frappe.utils import get_datetime, get_system_timezone, now_datetime


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


@frappe.whitelist()
def get_course_access_overview(course):
	"""Return access status and grants for the administrator's course screen."""
	frappe.only_for("System Manager")
	frappe.has_permission("LMS Access Grant", "read", throw=True)
	if not isinstance(course, str) or not frappe.db.exists("LMS Course", course):
		frappe.throw(_("Course not found."), frappe.ValidationError)
	policy = frappe.db.get_value("LMS Access Policy", {"course": course}, ["name", "enabled"], as_dict=True)
	grants = frappe.get_all("LMS Access Grant", filters={"course": course},
		fields=["name", "member", "status", "starts_at", "ends_at"], order_by="modified desc", limit_page_length=201)
	lessons = frappe.get_all("Course Lesson", filters={"course": course},
		fields=["name", "title"], order_by="name asc", limit_page_length=501)
	return {
		"release_enabled": frappe.conf.get("individual_access_release_enabled") is True,
		"policy_enabled": bool(policy and policy.enabled),
		"policy_exists": bool(policy),
		"timezone": get_system_timezone(),
		"grants": grants[:200],
		"truncated": len(grants) > 200,
		"lessons": lessons[:500],
		"lessons_truncated": len(lessons) > 500,
	}


@frappe.whitelist(methods=["POST"])
def create_course_access_policy(course):
	"""Create a disabled, unconfigured policy without changing student access."""
	frappe.only_for("System Manager")
	frappe.has_permission("LMS Access Policy", "create", throw=True)
	if not isinstance(course, str) or not frappe.db.get_value("LMS Course", course, "name", for_update=True):
		frappe.throw(_("Course not found."), frappe.ValidationError)
	if frappe.db.exists("LMS Access Policy", {"course": course}):
		frappe.throw(_("The course already has an access policy."), frappe.ValidationError)
	lessons = frappe.get_all("Course Lesson", filters={"course": course}, pluck="name")
	policy = frappe.get_doc({"doctype": "LMS Access Policy", "course": course, "enabled": 0,
		"lessons": [{"lesson": lesson, "opening_type": "Unknown", "prerequisite_type": "Unknown"}
			for lesson in lessons]}).insert()
	return {"name": policy.name, "enabled": False, "lesson_count": len(policy.lessons)}


@frappe.whitelist(methods=["POST"])
def create_grant_for_enrolled_student(course, member, starts_at, lessons):
	"""Create one inherited access grant for an already enrolled student.

	Enrollment and email delivery are deliberately outside this action. Existing
	grants are never changed: an administrator must inspect them first.
	"""
	frappe.only_for("System Manager")
	frappe.has_permission("LMS Access Grant", "create", throw=True)
	if not all(isinstance(value, str) and value.strip() for value in (course, member, starts_at)):
		frappe.throw(_("Course, student and start time are required."), frappe.ValidationError)
	if isinstance(lessons, str):
		lessons = frappe.parse_json(lessons)
	if not isinstance(lessons, list) or not lessons or any(not isinstance(x, str) or not x for x in lessons):
		frappe.throw(_("Select at least one lesson."), frappe.ValidationError)
	if len(set(lessons)) != len(lessons):
		frappe.throw(_("The lesson list contains duplicates."), frappe.ValidationError)
	starts_at = get_datetime(starts_at)
	# Serialize concurrent requests for this course, including duplicate checks.
	if not frappe.db.get_value("LMS Course", course, "name", for_update=True):
		frappe.throw(_("Course not found."), frappe.ValidationError)
	if not frappe.db.exists("LMS Enrollment", {"course": course, "member": member}):
		frappe.throw(_("The student must already be enrolled in the course."), frappe.ValidationError)
	if not frappe.db.exists("LMS Access Policy", {"course": course}):
		frappe.throw(_("Set up the course access policy first."), frappe.ValidationError)
	if frappe.db.exists("LMS Access Grant", {"course": course, "member": member, "status": ("!=", "Revoked")}):
		frappe.throw(_("This student already has an access grant for the course."), frappe.ValidationError)
	grant = frappe.get_doc({
		"doctype": "LMS Access Grant", "course": course, "member": member,
		"starts_at": starts_at, "status": "Active", "personal_end_type": "Inherit",
		"course_end_type": "Inherit", "completed_retention_type": "Inherit",
		"lessons": [{"lesson": lesson, "opening_type": "Inherit", "prerequisite_state": "Inherit"}
			for lesson in lessons],
	}).insert()
	return {"name": grant.name, "status": grant.status, "lesson_count": len(grant.lessons)}


@frappe.whitelist(methods=["POST"])
def revoke_grant(name):
	"""Close one grant while preserving all enrollment, progress and homework."""
	grant = _admin_grant(name)
	if grant.status not in ("Active", "Frozen", "Limited"):
		frappe.throw(_("Only active, frozen or limited access can be closed."), frappe.ValidationError)
	grant.status = "Revoked"
	grant.frozen_at = None
	grant.save()
	return {"name": grant.name, "status": grant.status}


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
	if extend:
		from lms.lms.individual_access import resolve_end

		kind, value, days = grant.personal_end_type, grant.ends_at, grant.personal_end_days
		if kind == "Inherit":
			policy = frappe.db.get_value("LMS Access Policy", {"course": grant.course, "enabled": 1},
				["default_personal_end_type", "default_personal_end_at", "default_personal_end_days"], as_dict=True)
			kind, value, days = ((policy.default_personal_end_type, policy.default_personal_end_at,
				policy.default_personal_end_days) if policy else ("Unknown", None, 0))
		kind, value = resolve_end(kind, value, days, grant.starts_at)
		if kind == "Unknown" or (kind == "At" and not value):
			frappe.throw(_("The personal end is unknown and cannot be extended."), frappe.ValidationError)
		if kind == "At":
			grant.personal_end_type = "At"
			grant.personal_end_days = 0
			grant.ends_at = get_datetime(value) + elapsed
	grant.status = "Active"
	grant.frozen_at = None
	grant.save()
	return {"name": grant.name, "status": grant.status, "personal_end": grant.ends_at}


@frappe.whitelist(methods=["POST"])
def limit_grant(name, retained_lessons, retention_end_type, retention_ends_at=None):
	"""Close a grant except explicit assigned lessons; never delete learning data."""
	if isinstance(retained_lessons, str):
		retained_lessons = frappe.parse_json(retained_lessons)
	if not isinstance(retained_lessons, list) or any(not isinstance(value, str) or not value for value in retained_lessons):
		frappe.throw(_("Explicitly select the lessons to keep."), frappe.ValidationError)
	selected = set(retained_lessons)
	if len(selected) != len(retained_lessons):
		frappe.throw(_("The retained lesson list contains duplicates."), frappe.ValidationError)
	if retention_end_type not in ("Unlimited", "At") or (retention_end_type == "At") != bool(retention_ends_at):
		frappe.throw(_("Select an unlimited or a fixed retained-access end."), frappe.ValidationError)
	if retention_ends_at and get_datetime(retention_ends_at) <= now_datetime():
		frappe.throw(_("Retained access must end in the future."), frappe.ValidationError)
	grant = _admin_grant(name)
	if grant.status not in ("Active", "Frozen"):
		frappe.throw(_("Only active or frozen access can be limited."), frappe.ValidationError)
	if not selected.issubset({row.lesson for row in grant.lessons}):
		frappe.throw(_("A retained lesson is not assigned to this grant."), frappe.ValidationError)
	for row in grant.lessons:
		keep = row.lesson in selected
		row.retain_when_limited = int(keep)
		row.retention_end_type = retention_end_type if keep else "Unknown"
		row.retention_ends_at = retention_ends_at if keep else None
	grant.status = "Limited"
	grant.frozen_at = None
	grant.save()
	return {"name": grant.name, "status": grant.status, "retained_count": len(selected)}

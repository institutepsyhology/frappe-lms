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


def _explicit_choice(value, message=None):
	if value is True or value == "1" or type(value) is int and value == 1:
		return True
	if value is False or value == "0" or type(value) is int and value == 0:
		return False
	frappe.throw(_(message or "Choose explicitly whether to extend the personal end date."), frappe.ValidationError)


@frappe.whitelist()
def get_course_access_overview(course):
	"""Return access status and grants for the administrator's course screen."""
	frappe.only_for("System Manager")
	frappe.has_permission("LMS Access Grant", "read", throw=True)
	if not isinstance(course, str) or not frappe.db.exists("LMS Course", course):
		frappe.throw(_("Course not found."), frappe.ValidationError)
	policy = frappe.db.get_value("LMS Access Policy", {"course": course}, ["name", "enabled",
		"default_personal_end_type", "default_personal_end_at", "default_personal_end_days",
		"global_end_type", "global_end_at", "completed_retention_type", "completed_retention_days",
		"visited_retention_type", "visited_retention_days"], as_dict=True)
	grants = frappe.get_all("LMS Access Grant", filters={"course": course},
		fields=["name", "member", "status", "starts_at", "personal_end_type", "ends_at",
			"personal_end_days", "ignore_course_end", "visited_retention_type", "visited_retention_days"], order_by="modified desc", limit_page_length=201)
	lessons = frappe.get_all("Course Lesson", filters={"course": course},
		fields=["name", "title"], order_by="name asc", limit_page_length=501)
	schedule = frappe.get_all("LMS Access Policy Lesson", filters={"parent": policy.name,
		"parenttype": "LMS Access Policy", "parentfield": "lessons"},
		fields=["lesson", "opening_type", "opens_at", "delay_days", "prerequisite_type",
			"prerequisite_lesson", "prerequisite_assignment"], limit_page_length=0) if policy else []
	return {
		"release_enabled": frappe.conf.get("individual_access_release_enabled") is True,
		"policy_enabled": bool(policy and policy.enabled),
		"policy_exists": bool(policy),
		"policy": policy,
		"timezone": get_system_timezone(),
		"grants": grants[:200],
		"truncated": len(grants) > 200,
		"lessons": lessons[:500],
		"lessons_truncated": len(lessons) > 500,
		"schedule": schedule,
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
def update_course_access_defaults(course, defaults):
	"""Save explicit course-wide defaults only while the policy is disabled."""
	frappe.only_for("System Manager")
	if isinstance(defaults, str):
		defaults = frappe.parse_json(defaults)
	fields = {"default_personal_end_type", "default_personal_end_at", "default_personal_end_days",
		"global_end_type", "global_end_at", "completed_retention_type", "completed_retention_days"}
	visit_fields = {"visited_retention_type", "visited_retention_days"}
	if not isinstance(defaults, dict) or set(defaults) not in (fields, fields | visit_fields):
		frappe.throw(_("Provide all course access defaults explicitly."), frappe.ValidationError)
	if not isinstance(course, str) or not frappe.db.get_value("LMS Course", course, "name", for_update=True):
		frappe.throw(_("Course not found."), frappe.ValidationError)
	name = frappe.db.get_value("LMS Access Policy", {"course": course}, "name", for_update=True)
	if not name:
		frappe.throw(_("Set up the course access policy first."), frappe.ValidationError)
	policy = frappe.get_doc("LMS Access Policy", name, for_update=True)
	policy.check_permission("write")
	if policy.enabled:
		frappe.throw(_("Disable the policy before editing its defaults."), frappe.ValidationError)
	policy.update(defaults)
	policy.save()
	return {"name": policy.name, "enabled": False}


@frappe.whitelist(methods=["POST"])
def update_grant_visited_retention(name, retention_type, retention_days):
	"""Set retention of previously visited lessons for one grant."""
	grant = _admin_grant(name)
	if grant.status not in ("Draft", "Active", "Frozen", "Limited"):
		frappe.throw(_("A closed access grant cannot be edited."), frappe.ValidationError)
	grant.visited_retention_type = retention_type
	grant.visited_retention_days = retention_days
	grant.save()
	return {"name": grant.name, "status": grant.status}


@frappe.whitelist(methods=["POST"])
def update_course_lesson_rule(course, lesson, rule):
	"""Save a lesson's opening and prerequisite rule on a disabled policy."""
	frappe.only_for("System Manager")
	if isinstance(rule, str):
		rule = frappe.parse_json(rule)
	fields = {"opening_type", "opens_at", "delay_days", "prerequisite_type", "prerequisite_lesson", "prerequisite_assignment"}
	if not isinstance(rule, dict) or set(rule) != fields:
		frappe.throw(_("Provide the complete lesson access rule."), frappe.ValidationError)
	if not isinstance(course, str) or not frappe.db.get_value("LMS Course", course, "name", for_update=True):
		frappe.throw(_("Course not found."), frappe.ValidationError)
	name = frappe.db.get_value("LMS Access Policy", {"course": course}, "name", for_update=True)
	if not name:
		frappe.throw(_("Set up the course access policy first."), frappe.ValidationError)
	policy = frappe.get_doc("LMS Access Policy", name, for_update=True)
	policy.check_permission("write")
	if policy.enabled:
		frappe.throw(_("Disable the policy before editing its lesson rules."), frappe.ValidationError)
	if frappe.db.get_value("Course Lesson", lesson, "course") != course:
		frappe.throw(_("The lesson does not belong to this course."), frappe.ValidationError)
	row = next((item for item in policy.lessons if item.lesson == lesson), None)
	if not row:
		row = policy.append("lessons", {"lesson": lesson})
	row.update(rule)
	policy.save()
	return {"name": policy.name, "lesson": lesson, "enabled": False}


@frappe.whitelist()
def get_lesson_assignments(course, lesson):
	"""List assignments actually placed in a course lesson for administrators."""
	frappe.only_for("System Manager")
	frappe.has_permission("LMS Access Policy", "read", throw=True)
	if frappe.db.get_value("Course Lesson", lesson, "course") != course:
		frappe.throw(_("The lesson does not belong to this course."), frappe.ValidationError)
	from lms.lms.utils import get_editorjs_blocks

	content = frappe.db.get_value("Course Lesson", lesson, "content")
	names = set()
	for block in get_editorjs_blocks(content):
		if isinstance(block, dict) and block.get("type") == "assignment" and isinstance(block.get("data"), dict):
			name = block["data"].get("assignment")
			if isinstance(name, str) and name:
				names.add(name)
	return frappe.get_all("LMS Assignment", filters={"name": ("in", list(names))},
		fields=["name", "title"], limit_page_length=0) if names else []


@frappe.whitelist()
def get_grant_lessons(name):
	"""List the lessons assigned to one personal access grant."""
	frappe.only_for("System Manager")
	if not isinstance(name, str) or not name:
		frappe.throw(_("A grant name is required."), frappe.ValidationError)
	grant = frappe.get_doc("LMS Access Grant", name)
	grant.check_permission("read")
	return [{"lesson": row.lesson, "title": frappe.db.get_value("Course Lesson", row.lesson, "title"),
		"manual_open": bool(row.manual_open), "retain_when_limited": bool(row.retain_when_limited)}
		for row in grant.lessons]


@frappe.whitelist(methods=["POST"])
def set_grant_lesson_manual_open(name, lesson, enabled):
	"""Explicitly open or restore the schedule for one assigned lesson."""
	grant = _admin_grant(name)
	if grant.status not in ("Draft", "Active", "Frozen", "Limited"):
		frappe.throw(_("A closed access grant cannot be edited."), frappe.ValidationError)
	value = _explicit_choice(enabled, "Choose explicitly whether to open the lesson early.")
	row = next((item for item in grant.lessons if item.lesson == lesson), None)
	if not row:
		frappe.throw(_("The lesson is not assigned to this grant."), frappe.ValidationError)
	row.manual_open = int(value)
	grant.save()
	return {"name": grant.name, "lesson": lesson, "manual_open": value}


@frappe.whitelist(methods=["POST"])
def set_grant_assigned_lessons(name, lessons):
	"""Change one grant's lesson list without deleting progress or homework."""
	if isinstance(lessons, str):
		lessons = frappe.parse_json(lessons)
	if not isinstance(lessons, list) or any(not isinstance(item, str) or not item for item in lessons):
		frappe.throw(_("Provide the lesson list explicitly."), frappe.ValidationError)
	selected = set(lessons)
	if len(selected) != len(lessons):
		frappe.throw(_("The lesson list contains duplicates."), frappe.ValidationError)
	grant = _admin_grant(name)
	if grant.status not in ("Draft", "Active", "Frozen"):
		frappe.throw(_("Only draft, active or frozen access can change its assigned lessons."), frappe.ValidationError)
	for lesson in lessons:
		if frappe.db.get_value("Course Lesson", lesson, "course") != grant.course:
			frappe.throw(_("Every lesson must belong to the selected course."), frappe.ValidationError)
	retained = [row for row in grant.lessons if row.lesson in selected]
	existing = {row.lesson for row in retained}
	grant.set("lessons", retained)
	for lesson in lessons:
		if lesson not in existing:
			grant.append("lessons", {"lesson": lesson, "opening_type": "Inherit", "prerequisite_state": "Inherit"})
	grant.save()
	return {"name": grant.name, "lesson_count": len(grant.lessons)}


@frappe.whitelist()
def preview_course_restart(name):
	"""Count this learner's course records without changing or deleting them."""
	grant = _admin_grant(name)
	lessons = frappe.get_all("Course Lesson", filters={"course": grant.course}, pluck="name")
	homework = frappe.db.count("LMS Assignment Submission", {"member": grant.member,
		"lesson": ("in", lessons)}) if lessons else 0
	return {
		"progress": frappe.db.count("LMS Course Progress", {"member": grant.member, "course": grant.course}),
		"homework": homework,
		"quiz_submissions": frappe.db.count("LMS Quiz Submission", {"member": grant.member, "course": grant.course}),
		"video_progress": frappe.db.count("LMS Video Watch Duration", {"member": grant.member,
			"lesson": ("in", lessons)}) if lessons else 0,
		"visits": frappe.db.count("LMS Lesson Visit", {"member": grant.member, "course": grant.course}),
		"other_grants": frappe.db.count("LMS Access Grant", {"member": grant.member, "course": grant.course,
			"name": ("!=", grant.name), "status": ("in", ["Draft", "Active", "Frozen", "Limited"])}),
		"enrolled": bool(frappe.db.exists("LMS Enrollment", {"member": grant.member, "course": grant.course})),
	}


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
def update_grant_timing(name, starts_at, personal_end_type, ends_at, personal_end_days, ignore_course_end):
	"""Set one grant's start and personal end without changing learning records."""
	grant = _admin_grant(name)
	if grant.status not in ("Draft", "Active", "Frozen", "Limited"):
		frappe.throw(_("A closed access grant cannot be edited."), frappe.ValidationError)
	if not isinstance(starts_at, str) or not starts_at:
		frappe.throw(_("A start time is required."), frappe.ValidationError)
	ignore = _explicit_choice(ignore_course_end, "Choose explicitly whether to ignore the course end.")
	if personal_end_type not in ("Unknown", "Inherit", "Unlimited", "At", "After Start"):
		frappe.throw(_("Choose a valid personal end rule."), frappe.ValidationError)
	grant.starts_at = get_datetime(starts_at)
	grant.personal_end_type = personal_end_type
	grant.ends_at = ends_at or None
	grant.personal_end_days = personal_end_days
	grant.ignore_course_end = int(ignore)
	grant.save()
	return {"name": grant.name, "status": grant.status}


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

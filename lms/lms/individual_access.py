"""Experimental grant reader. Not wired to LMS endpoints or enabled in production.

The caller must independently establish enrollment and course authorship. This
module deliberately does not fall back to enrollment when a decision is unknown.
Times are stored and compared in the site's configured time zone, as Frappe
Datetime fields and now_datetime() use the same site clock.
"""

from datetime import timedelta

import frappe
from frappe.utils import get_datetime, now_datetime


def protected_courses():
	"""The server switch and a course-specific record must both be enabled."""
	if frappe.conf.get("individual_access_release_enabled") is not True:
		return ()
	return tuple(frappe.db.get_all("LMS Access Policy", filters={"enabled": 1}, pluck="course"))


def policy_applies(course):
	return course in protected_courses()


def restrict_member_lesson(*, course, lesson, user, enrolled):
	"""Narrow enrollment for a future selected course; never create enrollment."""
	if not enrolled:
		return False
	if not policy_applies(course):
		return True
	return grant_allows_lesson(user=user, lesson=lesson)


def mask_inaccessible_outline(outline, can_access):
	"""Withhold lesson media identifiers from an already constructed outline."""
	for chapter in outline:
		for lesson in chapter.lessons:
			if not can_access(lesson.name):
				lesson.locked = 1
				lesson.youtube = None
				lesson.quiz_id = None
				lesson.question = None
	return outline


def assignment_in_lesson(assignment, blocks):
	"""A submitted lesson is valid only if it actually contains this assignment."""
	return any(
		isinstance(block, dict)
		and block.get("type") == "assignment"
		and isinstance(block.get("data"), dict)
		and block["data"].get("assignment") == assignment
		for block in blocks
	)


def quiz_in_lesson(quiz, blocks):
	for block in blocks:
		if not isinstance(block, dict) or not isinstance(block.get("data"), dict):
			continue
		data = block["data"]
		if block.get("type") == "quiz" and data.get("quiz") == quiz:
			return True
		if block.get("type") == "upload" and isinstance(data.get("quizzes"), list):
			if any(isinstance(item, dict) and item.get("quiz") == quiz for item in data["quizzes"]):
				return True
	return False


def schedule_opening(rule, starts_at):
	"""Resolve known opening rules; unknown or inconsistent values fail closed."""
	if not rule:
		return None
	if rule.opening_type == "At":
		return get_datetime(rule.opens_at) if rule.opens_at and not rule.delay_days else None
	if rule.opening_type == "After Start":
		if rule.opens_at or not starts_at or type(rule.delay_days) is not int or rule.delay_days < 0:
			return None
		return get_datetime(starts_at) + timedelta(days=rule.delay_days)
	return None


def prerequisite_satisfied(rule, *, member, course):
	"""Check the current member's prior progress or an actual lesson assignment."""
	if not rule or rule.prerequisite_type == "Unknown":
		return False
	if rule.prerequisite_type == "None":
		return not rule.prerequisite_lesson and not rule.prerequisite_assignment
	prior = rule.prerequisite_lesson
	if not prior or frappe.db.get_value("Course Lesson", prior, "course") != course:
		return False
	if rule.prerequisite_type == "Lesson Complete":
		return not rule.prerequisite_assignment and bool(frappe.db.exists(
			"LMS Course Progress", {"member": member, "course": course, "lesson": prior, "status": "Complete"}
		))
	if rule.prerequisite_type not in ("Assignment Submitted", "Assignment Passed") or not rule.prerequisite_assignment:
		return False
	from lms.lms.utils import get_editorjs_blocks

	content = frappe.db.get_value("Course Lesson", prior, "content")
	if not assignment_in_lesson(rule.prerequisite_assignment, get_editorjs_blocks(content)):
		return False
	filters = {"member": member, "lesson": prior, "assignment": rule.prerequisite_assignment}
	if rule.prerequisite_type == "Assignment Passed":
		filters["status"] = "Pass"
	return bool(frappe.db.exists("LMS Assignment Submission", filters))


def validate_prerequisite(course, row):
	kind, prior, assignment = row.prerequisite_type, row.prerequisite_lesson, row.prerequisite_assignment
	if kind in ("Unknown", "None"):
		if prior or assignment:
			frappe.throw("This prerequisite does not accept a lesson or assignment.")
		return
	if kind not in ("Lesson Complete", "Assignment Submitted", "Assignment Passed"):
		frappe.throw("Unknown prerequisite rule.")
	if not prior or prior == row.lesson or frappe.db.get_value("Course Lesson", prior, "course") != course:
		frappe.throw("Choose another lesson from the same course as the prerequisite.")
	if (kind in ("Assignment Submitted", "Assignment Passed")) != bool(assignment):
		frappe.throw("Choose an assignment only for an assignment prerequisite.")
	if assignment:
		from lms.lms.utils import get_editorjs_blocks

		if not assignment_in_lesson(assignment, get_editorjs_blocks(frappe.db.get_value("Course Lesson", prior, "content"))):
			frappe.throw("The prerequisite assignment must be present in the selected lesson.")


def validate_schedule_rows(course, rows, *, inherit_allowed):
	"""Reject unrelated, duplicate or contradictory lesson schedules."""
	seen = set()
	for row in rows or []:
		if not row.lesson or row.lesson in seen:
			frappe.throw("Each lesson must appear at most once in a schedule.")
		seen.add(row.lesson)
		if frappe.db.get_value("Course Lesson", row.lesson, "course") != course:
			frappe.throw("Every lesson must belong to the selected course.")
		kind = row.opening_type
		valid_types = {"Unknown", "At", "After Start"} | ({"Inherit"} if inherit_allowed else set())
		if kind not in valid_types or (kind == "At") != bool(row.opens_at):
			frappe.throw("The opening rule and opening date do not match.")
		days = row.delay_days or 0
		if type(days) is not int or days < 0 or (kind != "After Start" and days != 0):
			frappe.throw("The opening delay must be a non-negative number of days for a relative rule.")


def validate_end_rule(kind, value, days=0, *, inherit_allowed=False, duration_allowed=False):
	types = {"Unknown", "Unlimited", "At"}
	if inherit_allowed:
		types.add("Inherit")
	if duration_allowed:
		types.add("After Start")
	days = days or 0
	if (kind not in types or (kind == "At") != bool(value) or type(days) is not int
			or (kind == "After Start" and days <= 0) or (kind != "After Start" and days != 0)):
		frappe.throw("The access end rule, date and duration do not match.")


def resolve_end(kind, value, days, starts_at):
	if kind == "After Start":
		if value or not starts_at or type(days) is not int or days <= 0:
			return "Unknown", None
		return "At", get_datetime(starts_at) + timedelta(days=days)
	if kind in ("Unknown", "Unlimited", "At") and not days:
		return kind, value
	return "Unknown", None


def validate_retention(kind, days, *, inherit_allowed=False):
	valid = {"None", "Unlimited", "Days"} | ({"Inherit"} if inherit_allowed else set())
	days = days or 0
	if kind not in valid or type(days) is not int or (kind == "Days" and days <= 0) or (kind != "Days" and days != 0):
		frappe.throw("The completed-lesson retention rule and duration do not match.")


def _valid_end(kind, value, now):
	if kind == "Unlimited":
		return not value
	if kind != "At" or not value:
		return False
	return now < get_datetime(value)


def grant_allows_lesson(*, user, lesson, now=None, require_manual=False, require_retained=False):
	"""Check a persisted matching grant, failing closed on incomplete records.

	Unknown conditions fail closed; subscription integration is not implemented.
	"""
	if not isinstance(user, str) or not user or user == "Guest":
		return False
	if not isinstance(lesson, str) or not lesson:
		return False
	course = frappe.db.get_value("Course Lesson", lesson, "course")
	if not course:
		return False
	now = get_datetime(now if now is not None else now_datetime())
	grants = frappe.db.get_all(
		"LMS Access Grant",
		filters={"member": user, "course": course, "status": ("in", ["Active", "Limited"])},
		fields=["name", "status", "starts_at", "personal_end_type", "ends_at", "personal_end_days", "course_end_type",
			"course_ends_at", "ignore_course_end", "completed_retention_type", "completed_retention_days",
			"visited_retention_type", "visited_retention_days"],
	)
	for grant in grants:
		if not grant.starts_at or now < get_datetime(grant.starts_at):
			continue
		row = frappe.db.get_value(
			"LMS Access Grant Lesson",
			{"parent": grant.name, "parenttype": "LMS Access Grant", "parentfield": "lessons", "lesson": lesson},
			["opening_type", "opens_at", "delay_days", "prerequisite_state", "manual_open",
				"retain_when_limited", "retention_end_type", "retention_ends_at"],
			as_dict=True,
		)
		if not row:
			continue
		retained = False
		if grant.status == "Limited":
			if row.retain_when_limited != 1 or not _valid_end(row.retention_end_type, row.retention_ends_at, now):
				continue
			retained = True
		else:
			policy = None
			if (grant.personal_end_type == "Inherit" or grant.course_end_type == "Inherit"
					or grant.completed_retention_type == "Inherit" or grant.visited_retention_type == "Inherit"):
				policy = frappe.db.get_value(
					"LMS Access Policy", {"course": course, "enabled": 1},
					["default_personal_end_type", "default_personal_end_at", "default_personal_end_days",
						"global_end_type", "global_end_at", "completed_retention_type", "completed_retention_days",
						"visited_retention_type", "visited_retention_days"], as_dict=True,
				)
			personal_type, personal_at, personal_days = grant.personal_end_type, grant.ends_at, grant.personal_end_days
			if personal_type == "Inherit":
				personal_type, personal_at, personal_days = (
					(policy.default_personal_end_type, policy.default_personal_end_at, policy.default_personal_end_days)
					if policy else ("Unknown", None, 0)
				)
			personal_type, personal_at = resolve_end(personal_type, personal_at, personal_days, grant.starts_at)
			if grant.ignore_course_end not in (0, 1, False, True):
				continue
			course_type, course_at = grant.course_end_type, grant.course_ends_at
			if course_type == "Inherit":
				course_type, course_at = (policy.global_end_type, policy.global_end_at) if policy else ("Unknown", None)
			bounds = [(personal_type, personal_at)]
			if not grant.ignore_course_end:
				bounds.append((course_type, course_at))
			invalid = [(kind, at) for kind, at in bounds if not _valid_end(kind, at, now)]
			if invalid:
				# A missing/invalid bound is not an expired bound and cannot unlock retention.
				if any(kind != "At" or not at or now < get_datetime(at) for kind, at in invalid):
					continue
				closed_at = min(get_datetime(at) for _, at in invalid)
				def in_window(kind, days):
					return (kind == "Unlimited" and not days) or (kind == "Days" and type(days) is int
						and days > 0 and now < closed_at + timedelta(days=days))
				completed, days = grant.completed_retention_type, grant.completed_retention_days
				if completed == "Inherit":
					completed, days = ((policy.completed_retention_type, policy.completed_retention_days)
						if policy else ("None", 0))
				visited, visit_days = grant.visited_retention_type, grant.visited_retention_days
				if visited == "Inherit":
					visited, visit_days = ((policy.visited_retention_type, policy.visited_retention_days)
						if policy else ("None", 0))
				completed_ok = in_window(completed, days) and frappe.db.exists("LMS Course Progress",
					{"member": user, "course": course, "lesson": lesson, "status": "Complete"})
				visited_ok = in_window(visited, visit_days) and frappe.db.exists("LMS Lesson Visit",
					{"member": user, "course": course, "lesson": lesson, "creation": ("<=", closed_at)})
				if not completed_ok and not visited_ok:
					continue
				retained = True
		if retained:
			if not require_manual:
				return True
			if row.manual_open == 1:
				return True
			continue
		if require_retained:
			continue
		if row.manual_open == 1:
			return True
		if require_manual:
			continue
		policy_rule = None
		if row.opening_type == "Inherit" or row.prerequisite_state == "Inherit":
			policy = frappe.db.get_value("LMS Access Policy", {"course": course, "enabled": 1}, "name")
			policy_rule = frappe.db.get_value(
				"LMS Access Policy Lesson",
				{"parent": policy, "parenttype": "LMS Access Policy", "parentfield": "lessons", "lesson": lesson},
				["opening_type", "opens_at", "delay_days", "prerequisite_type", "prerequisite_lesson", "prerequisite_assignment"], as_dict=True,
			) if policy else None
		rule = policy_rule if row.opening_type == "Inherit" else row
		opening = schedule_opening(rule, grant.starts_at)
		ready = (prerequisite_satisfied(policy_rule, member=user, course=course)
			if row.prerequisite_state == "Inherit" else row.prerequisite_state in ("Clear", "Satisfied"))
		if opening and now >= opening and ready:
			return True
	return False

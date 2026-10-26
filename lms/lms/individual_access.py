"""Experimental grant reader. Not wired to LMS endpoints or enabled in production.

The caller must independently establish enrollment and course authorship. This
module deliberately does not fall back to enrollment when a decision is unknown.
Times are stored and compared in the site's configured time zone, as Frappe
Datetime fields and now_datetime() use the same site clock.
"""

import frappe
from frappe.utils import get_datetime, now_datetime


def policy_applies(course):
	"""Release barrier: no course can opt in until every access route is covered."""
	return False


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


def _valid_end(kind, value, now):
	if kind == "Unlimited":
		return not value
	if kind != "At" or not value:
		return False
	return now < get_datetime(value)


def grant_allows_lesson(*, user, lesson, now=None):
	"""Check a persisted matching grant, failing closed on incomplete records.

	This does not implement access retention, subscriptions, homework-derived
	conditions or any exception to course closure; those must be designed and
	tested before the reader can be connected to production routes.
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
		filters={"member": user, "course": course, "status": "Active"},
		fields=["name", "starts_at", "personal_end_type", "ends_at", "course_end_type",
			"course_ends_at", "ignore_course_end"],
	)
	for grant in grants:
		if not grant.starts_at or now < get_datetime(grant.starts_at):
			continue
		if not _valid_end(grant.personal_end_type, grant.ends_at, now):
			continue
		if grant.ignore_course_end not in (0, 1, False, True):
			continue
		if not grant.ignore_course_end and not _valid_end(grant.course_end_type, grant.course_ends_at, now):
			continue
		row = frappe.db.get_value(
			"LMS Access Grant Lesson",
			{"parent": grant.name, "parenttype": "LMS Access Grant", "parentfield": "lessons", "lesson": lesson},
			["opens_at", "prerequisite_state", "manual_open"],
			as_dict=True,
		)
		if not row:
			continue
		if row.manual_open == 1:
			return True
		if row.opens_at and now >= get_datetime(row.opens_at) and row.prerequisite_state == "Clear":
			return True
	return False

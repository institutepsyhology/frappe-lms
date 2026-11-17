"""Capture verified learner visits without modifying course progress."""
from hashlib import sha256
import json

import frappe


def learner_activity_allowed():
	"""Server session provenance, never a client-supplied preview flag."""
	user = frappe.session.user
	if user in ("Guest", "Administrator"):
		return False
	data = getattr(frappe.session, "data", None) or {}
	if data.get("impersonated_by"):
		return False
	return not set(frappe.get_roles(user)).intersection(
		{"System Manager", "Moderator", "Course Creator", "Batch Evaluator"}
	)


@frappe.whitelist(methods=["POST"])
def record_lesson_visit(course, lesson):
	user = frappe.session.user
	if not isinstance(course, str) or not isinstance(lesson, str) or not learner_activity_allowed():
		return {"recorded": False}
	if frappe.db.get_value("Course Lesson", lesson, "course") != course:
		frappe.throw("Lesson does not belong to this course.", frappe.PermissionError)
	from lms.lms.permissions import can_access_lesson, get_lesson_gate
	from lms.lms.utils import can_modify_course, get_membership

	if can_modify_course(course) or not get_membership(course, user):
		return {"recorded": False}
	locked, _ = get_lesson_gate(course)
	if lesson in locked or not can_access_lesson(lesson):
		frappe.throw("This lesson is not available to you.", frappe.PermissionError)
	key = sha256(json.dumps([user, course, lesson], ensure_ascii=True, separators=(",", ":")).encode()).hexdigest()
	from frappe.utils import now_datetime
	now = now_datetime()
	if not frappe.db.exists("LMS Lesson Visit", key):
		frappe.get_doc({"doctype": "LMS Lesson Visit", "visit_key": key,
			"member": user, "course": course, "lesson": lesson,
			"first_learner_visit_at": now, "last_learner_visit_at": now}).insert(ignore_permissions=True, ignore_if_duplicate=True)
	# Atomic updates preserve the first verified event, including concurrent tabs.
	frappe.db.sql("""UPDATE `tabLMS Lesson Visit`
		SET first_learner_visit_at=COALESCE(first_learner_visit_at,%s),
		last_learner_visit_at=GREATEST(COALESCE(last_learner_visit_at,%s),%s)
		WHERE name=%s""", (now, now, now, key))
	return {"recorded": True}

"""Capture verified learner visits without modifying course progress."""
from hashlib import sha256
import json

import frappe


@frappe.whitelist(methods=["POST"])
def record_lesson_visit(course, lesson):
	user = frappe.session.user
	from lms.lms.individual_access import policy_applies

	if not isinstance(course, str) or not isinstance(lesson, str) or user == "Guest" or not policy_applies(course):
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
	if not frappe.db.exists("LMS Lesson Visit", key):
		frappe.get_doc({"doctype": "LMS Lesson Visit", "visit_key": key,
			"member": user, "course": course, "lesson": lesson}).insert(ignore_permissions=True, ignore_if_duplicate=True)
	return {"recorded": True}

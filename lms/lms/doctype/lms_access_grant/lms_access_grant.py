import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import get_datetime


class LMSAccessGrant(Document):
	"""Administrative record only; does not yet enforce lesson permissions."""

	def validate(self):
		for end_type, value in ((self.personal_end_type, self.ends_at), (self.course_end_type, self.course_ends_at)):
			if end_type not in ("Unknown", "Unlimited", "At") or (end_type == "At") != bool(value):
				frappe.throw(_("Choose a valid end type and provide a date only for a fixed end."))
		if self.starts_at and self.ends_at and get_datetime(self.ends_at) <= get_datetime(self.starts_at):
			frappe.throw(_("The access end must be later than the start."))
		seen = set()
		for row in self.lessons or []:
			if row.lesson in seen:
				frappe.throw(_("A lesson cannot appear twice in the same access grant."))
			seen.add(row.lesson)
			course = frappe.db.get_value("Course Lesson", row.lesson, "course")
			if not course or course != self.course:
				frappe.throw(_("Every lesson must belong to the selected course."))

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import get_datetime


class LMSAccessGrant(Document):
	"""Administrative record only; does not yet enforce lesson permissions."""

	def validate(self):
		if self.status == "Frozen" and not self.frozen_at:
			frappe.throw(_("A frozen access grant must have a freeze time."))
		from lms.lms.individual_access import validate_end_rule, validate_retention

		validate_end_rule(self.personal_end_type, self.ends_at, self.personal_end_days,
			inherit_allowed=True, duration_allowed=True)
		validate_end_rule(self.course_end_type, self.course_ends_at, inherit_allowed=True)
		validate_retention(self.completed_retention_type, self.completed_retention_days, inherit_allowed=True)
		if self.starts_at and self.ends_at and get_datetime(self.ends_at) <= get_datetime(self.starts_at):
			frappe.throw(_("The access end must be later than the start."))
		from lms.lms.individual_access import validate_schedule_rows

		validate_schedule_rows(self.course, self.lessons, inherit_allowed=True)
		for row in self.lessons or []:
			if row.retain_when_limited:
				if row.retention_end_type not in ("Unlimited", "At") or (row.retention_end_type == "At") != bool(row.retention_ends_at):
					frappe.throw(_("Choose a valid end for retained lesson access."))
			elif row.retention_end_type != "Unknown" or row.retention_ends_at:
				frappe.throw(_("A non-retained lesson cannot have a retained-access end."))

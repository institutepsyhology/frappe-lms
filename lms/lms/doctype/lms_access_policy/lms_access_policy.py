from frappe.model.document import Document


class LMSAccessPolicy(Document):
	"""Explicit per-course opt-in; server release switch remains off by default."""

	def validate(self):
		from lms.lms.individual_access import validate_schedule_rows

		validate_schedule_rows(self.course, self.lessons, inherit_allowed=False)

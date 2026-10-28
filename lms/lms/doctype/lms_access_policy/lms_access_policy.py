from frappe.model.document import Document


class LMSAccessPolicy(Document):
	"""Explicit per-course opt-in; server release switch remains off by default."""

	def before_validate(self):
		if not self.visited_retention_type:
			self.visited_retention_type = "None"

	def validate(self):
		from lms.lms.individual_access import validate_end_rule, validate_prerequisite, validate_retention, validate_schedule_rows

		validate_end_rule(self.default_personal_end_type, self.default_personal_end_at,
			self.default_personal_end_days, duration_allowed=True)
		validate_end_rule(self.global_end_type, self.global_end_at)
		validate_retention(self.completed_retention_type, self.completed_retention_days)
		validate_retention(self.visited_retention_type, self.visited_retention_days)
		validate_schedule_rows(self.course, self.lessons, inherit_allowed=False)
		for row in self.lessons or []:
			validate_prerequisite(self.course, row)

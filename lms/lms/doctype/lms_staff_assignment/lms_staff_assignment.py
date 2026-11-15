from frappe.model.document import Document


class LMSStaffAssignment(Document):
    def before_validate(self):
        from lms.lms.staff_positions import validate_assignment_document
        validate_assignment_document(self)

    def on_update(self):
        from lms.lms.staff_positions import assignment_updated
        assignment_updated(self)

    def on_trash(self):
        from lms.lms.staff_positions import prevent_assignment_delete
        prevent_assignment_delete(self)

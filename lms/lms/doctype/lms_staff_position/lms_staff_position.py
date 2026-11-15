import frappe
from frappe.model.document import Document


class LMSStaffPosition(Document):
    def before_validate(self):
        from lms.lms.staff_positions import validate_position_document
        validate_position_document(self)

    def on_update(self):
        from lms.lms.staff_positions import position_updated
        position_updated(self)

    def on_trash(self):
        from lms.lms.staff_positions import validate_position_delete
        validate_position_delete(self)

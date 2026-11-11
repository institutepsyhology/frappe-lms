"""Administrator-only, single-user import preserving an AVO password."""
import frappe
from frappe.utils import validate_email_address


def _insert_imported_user(user):
    """Bypass the hourly signup throttle only during this user's before_insert.

    The import flag is request-local and is restored before validation and all
    later lifecycle hooks. Ordinary registration remains throttled.
    """
    original = user.run_method

    def run_method(method, *args, **kwargs):
        if method != 'before_insert':
            return original(method, *args, **kwargs)
        previous = frappe.flags.in_import
        frappe.flags.in_import = True
        try:
            return original(method, *args, **kwargs)
        finally:
            frappe.flags.in_import = previous

    user.run_method = run_method
    try:
        user.insert(ignore_permissions=True)
    finally:
        del user.run_method


@frappe.whitelist(methods=["POST"])
def import_user(data):
    if frappe.session.user != "Administrator" or frappe.local.site != "my-lk.mv-centr.ru":
        frappe.throw("Administrator required", frappe.PermissionError)
    data = frappe.parse_json(data)
    if not isinstance(data, dict):
        frappe.throw("Invalid import data", frappe.ValidationError)
    allowed = {"email", "first_name", "middle_name", "last_name", "mobile_no", "new_password",
               "custom_avo_contact_id", "custom_avo_account", "custom_avo_telegram_id",
               "custom_avo_telegram_username", "custom_avo_vk_id", "custom_avo_vk_username"}
    if set(data) - allowed or data.get("custom_avo_account") != "mv-centr":
        frappe.throw("Invalid import data", frappe.ValidationError)
    email, password, source_id = data.get("email"), data.get("new_password"), data.get("custom_avo_contact_id")
    if not isinstance(email, str) or not validate_email_address(email, throw=False) or not isinstance(password, str) or not password or not str(source_id or "").isdigit():
        frappe.throw("Invalid import data", frappe.ValidationError)
    if frappe.db.exists("User", email.lower()) or frappe.db.exists("User", {"custom_avo_account": "mv-centr", "custom_avo_contact_id": str(source_id)}):
        frappe.throw("User already exists", frappe.DuplicateEntryError)
    user = frappe.get_doc({"doctype": "User", **data, "email": email.lower(),
                           "user_type": "Website User", "send_welcome_email": 0})
    user.flags.ignore_password_policy = True
    _insert_imported_user(user)
    from lms.lms.support_credentials import store_new_user_password
    store_new_user_password(user.name, password)
    return {"created": True}

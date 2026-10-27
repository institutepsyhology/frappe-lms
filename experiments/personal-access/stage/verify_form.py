"""Verify that Frappe includes the administrator controls in form metadata."""
import frappe
from frappe.desk.form.meta import get_meta

frappe.init(site="access-stage2.local")
frappe.connect()
try:
    frappe.set_user("Administrator")
    script = get_meta("LMS Access Grant", cached=False).get("__js") or ""
    required = ("freeze_grant", "resume_grant", "revoke_grant", "set_headline_alert")
    if not all(token in script for token in required):
        raise RuntimeError("The grant form is missing administrator controls")
    print("Grant form includes all administrator controls")
finally:
    frappe.destroy()

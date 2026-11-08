"""Run only on the isolated Frappe stage; create and roll back a synthetic user."""
import importlib.util
import sys
import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields
from frappe.utils.password import check_password

frappe.init(site="access-stage2.local")
frappe.connect()
try:
    frappe.set_user("Administrator")
    fields = [{"fieldname": name, "label": name, "fieldtype": "Data", "insert_after": "email"}
              for name in ("custom_avo_contact_id", "custom_avo_account", "custom_avo_telegram_id",
                           "custom_avo_telegram_username", "custom_avo_vk_id", "custom_avo_vk_username")]
    create_custom_fields({"User": fields}, update=True)
    frappe.db.commit()
    spec = importlib.util.spec_from_file_location("avo_user_import_stage", "/tmp/avo_user_import.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    data = {"email": "migration-test-20261108@example.invalid", "first_name": "Test", "new_password": "1234",
            "custom_avo_contact_id": "9911223344", "custom_avo_account": "mv-centr"}
    if frappe.db.exists("User", data["email"]):
        raise RuntimeError("synthetic user exists")
    original = frappe.local.site
    frappe.local.site = "my-lk.mv-centr.ru"
    try:
        mod.import_user(data)
    finally:
        frappe.local.site = original
    assert check_password(data["email"], data["new_password"]) == data["email"]
    try:
        frappe.local.site = "my-lk.mvcentr.invalid"
        mod.import_user(data)
        raise AssertionError("wrong site accepted")
    except frappe.PermissionError:
        pass
    finally:
        frappe.local.site = original
    print("STAGE_PASSWORD_AND_SITE_CHECK_PASSED")
finally:
    frappe.db.rollback()
    frappe.destroy()


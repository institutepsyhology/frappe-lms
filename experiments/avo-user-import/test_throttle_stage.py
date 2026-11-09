"""Test request-scoped throttle bypass against synthetic stage users only."""
import importlib.util
import json
import frappe
from frappe.utils.password import check_password

frappe.init(site='access-stage2.local')
frappe.connect()
try:
    frappe.set_user('Administrator')
    frappe.local.conf['throttle_user_limit'] = -1
    spec = importlib.util.spec_from_file_location('stage_import','/tmp/avo_user_import_20261109.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    normal = frappe.get_doc({'doctype':'User','email':'normal-stage@example.invalid','first_name':'Test',
                             'user_type':'Website User','send_welcome_email':0})
    try:
        normal.run_method('before_insert')
        raise RuntimeError('ordinary_signup_not_throttled')
    except frappe.ValidationError:
        pass
    email='avo-import-throttle-stage@example.invalid'
    if frappe.db.exists('User',email): raise RuntimeError('synthetic_user_exists')
    old_site=frappe.local.site
    try:
        frappe.local.site='my-lk.mv-centr.ru'
        module.import_user({'email':email,'first_name':'Synthetic','new_password':'StagePassword!123',
                            'custom_avo_contact_id':'9933881122','custom_avo_account':'mv-centr'})
    finally:
        frappe.local.site=old_site
    if frappe.flags.in_import: raise RuntimeError('import_flag_leaked')
    if check_password(email,'StagePassword!123')!=email: raise RuntimeError('password_login_failed')
    print(json.dumps({'ordinary_signup_throttled':True,'import_created':True,'password_login':True,'flag_restored':True,'rolled_back':True}))
finally:
    frappe.db.rollback()
    frappe.destroy()

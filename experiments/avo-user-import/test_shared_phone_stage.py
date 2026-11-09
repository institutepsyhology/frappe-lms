"""Stage-only transactional check: two distinct users may share one phone."""
import json
import frappe
from frappe.core.doctype.user.user import User

frappe.init(site='access-stage2.local')
frappe.connect()
try:
    frappe.set_user('Administrator')
    if int(frappe.get_meta('User').get_field('mobile_no').unique or 0):
        raise RuntimeError('shared_phone_not_enabled')
    emails = ('avo.shared.test.a@example.invalid', 'avo.shared.test.b@example.invalid')
    phone = '+19990000099'
    for email in emails:
        if frappe.db.exists('User', email): raise RuntimeError('test_user_exists')
        user = frappe.get_doc({'doctype':'User','email':email,'first_name':'Synthetic',
            'mobile_no':phone,'user_type':'Website User','send_welcome_email':0,'new_password':'StrongStagePass!123'})
        user.insert(ignore_permissions=True)
    if frappe.db.count('User', {'mobile_no':phone}) != 2: raise RuntimeError('shared_phone_not_saved')
    for email in emails:
        result = User.find_by_credentials(email,'StrongStagePass!123')
        if not result or result['name'] != email or not result['is_authenticated']:
            raise RuntimeError('email_login_failed')
    print(json.dumps({'two_users_same_phone':True,'email_login_for_both':True,'rolled_back':True}))
finally:
    frappe.db.rollback()
    frappe.destroy()

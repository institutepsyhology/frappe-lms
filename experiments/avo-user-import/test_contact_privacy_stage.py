"""Check whether one website user can read another contact on the stage."""
import json
import frappe

frappe.init(site='access-stage2.local');frappe.connect()
try:
    frappe.set_user('Administrator')
    user_email='avo-privacy-viewer-stage@example.invalid'
    if frappe.db.exists('User',user_email) or frappe.db.exists('Contact',{'custom_avo_contact_id':'993388199'}):
        raise RuntimeError('synthetic_identity_exists')
    user=frappe.get_doc({'doctype':'User','email':user_email,'first_name':'Synthetic',
                         'user_type':'Website User','send_welcome_email':0})
    user.insert(ignore_permissions=True)
    contact=frappe.get_doc({'doctype':'Contact','first_name':'Private synthetic',
                            'custom_avo_contact_id':'993388199','custom_avo_account':'mv-centr',
                            'custom_avo_vk_id':'123456789'})
    contact.insert(ignore_permissions=True)
    frappe.set_user(user_email)
    doc_read=bool(frappe.has_permission('Contact','read',contact))
    try:
        rows=frappe.get_list('Contact',filters={'name':contact.name},fields=['name'])
        listed=bool(rows)
    except frappe.PermissionError:
        listed=False
    print(json.dumps({'other_contact_readable':doc_read,'other_contact_listed':listed,'rolled_back':True}))
finally:
    frappe.db.rollback();frappe.destroy()

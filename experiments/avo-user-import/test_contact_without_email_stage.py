"""Check phone sharing and source-ID uniqueness on synthetic stage contacts."""
import json
import frappe

frappe.init(site='access-stage2.local')
frappe.connect()
try:
    frappe.set_user('Administrator')
    ids=('993388101','993388102')
    for ident in ids:
        if frappe.db.exists('Contact', {'custom_avo_contact_id':ident}):
            raise RuntimeError('synthetic_identity_exists')
        contact=frappe.get_doc({'doctype':'Contact','first_name':'Synthetic '+ident,
            'custom_avo_contact_id':ident,'custom_avo_account':'mv-centr',
            'custom_avo_telegram_id':'123456789',
            'phone_nos':[{'phone':'+19990000099','is_primary_mobile_no':1}]})
        contact.insert(ignore_permissions=True)
        if contact.email_id: raise RuntimeError('unexpected_email')
    rows=frappe.get_all('Contact',filters={'custom_avo_contact_id':['in',ids]},
                        fields=['custom_avo_contact_id','email_id','mobile_no'])
    if len(rows)!=2 or any(x.email_id or x.mobile_no!='+19990000099' for x in rows):
        raise RuntimeError('contact_data_mismatch')
    duplicate=frappe.get_doc({'doctype':'Contact','first_name':'Synthetic duplicate',
        'custom_avo_contact_id':ids[0],'custom_avo_account':'mv-centr'})
    try:
        duplicate.insert(ignore_permissions=True)
        raise RuntimeError('duplicate_identity_accepted')
    except (frappe.DuplicateEntryError, frappe.UniqueValidationError):
        pass
    print(json.dumps({'two_contacts_no_email':True,'same_phone':True,'duplicate_identity_rejected':True,'rolled_back':True}))
finally:
    frappe.db.rollback()
    frappe.destroy()

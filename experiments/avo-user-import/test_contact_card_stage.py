"""Exercise the card with synthetic records on the isolated stage."""
import importlib.util
import json
from frappe.utils.password import update_password, set_encrypted_password, get_decrypted_password
import frappe

frappe.init(site='access-stage2.local');frappe.connect()
try:
    spec=importlib.util.spec_from_file_location('card_test','/tmp/avo_contact_card_test.py')
    card=importlib.util.module_from_spec(spec);spec.loader.exec_module(card)
    frappe.set_user('Administrator')
    email='contact-card-stage@example.invalid'
    if frappe.db.exists('User',email):raise RuntimeError('synthetic_user_exists')
    user=frappe.get_doc({'doctype':'User','email':email,'first_name':'Synthetic','user_type':'Website User','send_welcome_email':0})
    user.insert(ignore_permissions=True)
    user.db_set('custom_avo_contact_id','993388411');user.db_set('custom_avo_account','mv-centr')
    c=frappe.get_doc({'doctype':'Contact','first_name':'Synthetic Contact','custom_avo_contact_id':'993388412',
        'custom_avo_account':'mv-centr','phone_nos':[{'phone':'+19990000001','is_primary_mobile_no':1}]})
    c.insert(ignore_permissions=True)
    assert any(item['name']==c.name for item in card.list_source_contacts(search='993388412'))
    result=card.get_card('User',email)
    assert result['custom_avo_contact_id']=='993388411' and 'reset_password_key' not in result
    saved=card.save_card('User',email,{'first_name':'Edited','custom_avo_telegram_id':'100'})
    assert saved['first_name']=='Edited' and saved['custom_avo_telegram_id']=='100'
    saved=card.save_card('Contact',c.name,{'mobile_no':'+19990000002','email':'contact-stage@example.invalid'})
    assert saved['mobile_no']=='+19990000002' and saved['email']=='contact-stage@example.invalid'
    try:
        card.save_card('User',email,{'custom_avo_contact_id':'1'})
        raise RuntimeError('identity_change_allowed')
    except frappe.ValidationError:
        pass
    assert card.courses_for_user(email)==[]
    if not frappe.db.exists('Role','LMS Credential Manager'):
        frappe.get_doc({'doctype':'Role','role_name':'LMS Credential Manager','desk_access':0}).insert(ignore_permissions=True)
    user.reload()
    user.add_roles('LMS Credential Manager')
    frappe.set_user(email)
    assert card.get_card('Contact',c.name)['custom_avo_contact_id']=='993388412'
    frappe.set_user('Administrator');user.reload();user.remove_roles('LMS Credential Manager')
    frappe.set_user(email)
    try:
        card.get_card('User',email)
        raise RuntimeError('student_read_card')
    except frappe.PermissionError:
        pass
    frappe.set_user('Administrator')
    new_email='contact-card-renamed-stage@example.invalid'
    if frappe.db.exists('User',new_email):raise RuntimeError('synthetic_new_user_exists')
    frappe.db.set_value('Contact',c.name,'user',email)
    enrollment=frappe.get_doc({'doctype':'LMS Enrollment','name':'contact-card-stage-enrollment',
                               'member':email,'course':'contact-card-stage-course'})
    enrollment.db_insert()
    update_password(email,'Stage Rename Password 621!')
    set_encrypted_password('User',email,'Stage Rename Password 621!','lms_support_password')
    assert card.change_user_email(email,new_email)['name']==new_email
    assert frappe.db.get_value('Contact',c.name,'user')==new_email
    assert frappe.db.get_value('LMS Enrollment','contact-card-stage-enrollment','member')==new_email
    assert frappe.db.get_value('User',new_email,'custom_avo_contact_id')=='993388411'
    assert get_decrypted_password('User',new_email,'lms_support_password')=='Stage Rename Password 621!'
    print(json.dumps({'user_edit':True,'contact_edit':True,'identity_protected':True,
        'student_denied':True,'credential_role_allowed':True,'email_rename_links_and_password':True,
        'no_secret_in_card':True,'courses_empty':True,'rolled_back':True}))
finally:
    frappe.db.rollback();frappe.destroy()

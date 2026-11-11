"""Exercise opt-outs with synthetic addresses on the isolated stage only."""
import importlib.util
import json
import sys
import frappe


def load(name, path):
    spec=importlib.util.spec_from_file_location(name, path)
    module=importlib.util.module_from_spec(spec); sys.modules[name]=module
    spec.loader.exec_module(module)
    return module


frappe.init(site='access-stage2.local'); frappe.connect()
try:
    frappe.set_user('Administrator')
    load('test_user_fields', '/tmp/marketing_user_fields.py').execute()
    load('test_contact_fields', '/tmp/marketing_contact_fields.py').execute()
    frappe.db.commit(); frappe.clear_cache()
    marketing=load('lms.lms.avo_marketing','/tmp/avo_marketing.py')
    card=load('test_avo_card','/tmp/avo_card.py')
    email='synthetic-optout-stage@example.invalid'
    if frappe.db.exists('User', email): raise RuntimeError('synthetic_user_exists')
    user=frappe.get_doc({'doctype':'User','email':email,'first_name':'Synthetic',
        'user_type':'Website User','send_welcome_email':0})
    user.insert(ignore_permissions=True)
    user.db_set('custom_avo_contact_id','993385000'); user.db_set('custom_avo_account','mv-centr')
    contact=frappe.get_doc({'doctype':'Contact','first_name':'Synthetic',
        'custom_avo_contact_id':'993385001','custom_avo_account':'mv-centr',
        'email_ids':[{'email_id':email,'is_primary':1}]})
    contact.insert(ignore_permissions=True)
    assert not marketing.is_blocked(email)
    group=frappe.get_doc({'doctype':'Email Group','title':'synthetic optout stage'}).insert(ignore_permissions=True)
    member=frappe.get_doc({'doctype':'Email Group Member','email_group':group.name,'email':email})
    member.insert(ignore_permissions=True)
    assert not member.unsubscribed
    contact.db_set('custom_no_marketing_email',1)
    marketing.protect_document(contact)
    assert frappe.db.get_value('Email Group Member',member.name,'unsubscribed')==1
    contact.db_set('custom_no_marketing_email',0)
    member.db_set('unsubscribed',0)
    assert marketing.apply_source_optouts('mv-centr',['993385001'])['processed']==1
    assert frappe.db.get_value('Contact',contact.name,'custom_no_marketing_email')==1
    assert frappe.db.get_value('Email Group Member',member.name,'unsubscribed')==1
    assert marketing.is_blocked(email)
    new_member=frappe.get_doc({'doctype':'Email Group Member','email':email,'email_group':group.name})
    marketing.protect_group_member(new_member)
    assert new_member.unsubscribed==1
    assert not frappe.db.exists('Email Unsubscribe', {'email':email,'global_unsubscribe':1})
    assert card.save_card('User',email,{'custom_no_marketing_email':True})['custom_no_marketing_email']
    try:
        marketing.apply_source_optouts('iomp',['993385000'])
        raise RuntimeError('wrong_account_accepted')
    except frappe.PermissionError:
        pass
    print(json.dumps({'source_optout':True,'shared_email_blocked':True,'existing_group_unsubscribed':True,
        'new_group_member_blocked':True,'transactional_unsubscribe_not_created':True,
        'card_edit':True,'cross_account_denied':True,'rolled_back':True}))
finally:
    frappe.db.rollback(); frappe.destroy()

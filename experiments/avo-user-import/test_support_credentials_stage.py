"""Exercise credential permissions with synthetic accounts on the isolated stage."""
import importlib.util
import json
import sys
import frappe
from frappe.utils.password import update_password

frappe.init(site='access-stage2.local')
frappe.connect()
try:
    spec=importlib.util.spec_from_file_location('support_credentials_test','/tmp/support_credentials_test.py')
    credentials=importlib.util.module_from_spec(spec);spec.loader.exec_module(credentials)
    import frappe.email.doctype.email_account.email_account as email_module
    old_muted=email_module.are_emails_muted
    email_module.are_emails_muted=lambda:True
    try:
        try:
            credentials.ensure_mail_ready()
            raise RuntimeError('muted_mail_allowed')
        except frappe.ValidationError:
            pass
    finally:
        email_module.are_emails_muted=old_muted
    sys.modules['lms.lms.support_credentials']=credentials
    card_spec=importlib.util.spec_from_file_location('card_test','/tmp/avo_contact_card_test.py')
    card=importlib.util.module_from_spec(card_spec);card_spec.loader.exec_module(card)
    frappe.set_user('Administrator')
    credentials.ensure_role()
    target='credential-target-stage@example.invalid'
    viewer='credential-viewer-stage@example.invalid'
    outsider='credential-outsider-stage@example.invalid'
    for email in (target,viewer,outsider):
        if frappe.db.exists('User',email):raise RuntimeError('synthetic_user_exists')
        u=frappe.get_doc({'doctype':'User','email':email,'first_name':'Synthetic',
            'user_type':'Website User','send_welcome_email':0})
        u.insert(ignore_permissions=True)
    importer_spec=importlib.util.spec_from_file_location('importer_test','/tmp/avo_user_import_test.py')
    importer=importlib.util.module_from_spec(importer_spec);importer_spec.loader.exec_module(importer)
    new_email='credential-import-stage@example.invalid'
    if frappe.db.exists('User',new_email):raise RuntimeError('synthetic_user_exists')
    created=frappe.get_doc({'doctype':'User','email':new_email,'first_name':'Synthetic',
        'user_type':'Website User','send_welcome_email':0,'new_password':'Imported Stage Password 683!'})
    created.flags.ignore_password_policy=True
    importer._insert_imported_user(created)
    credentials.store_new_user_password(created.name,'Imported Stage Password 683!')
    assert credentials._current_password(created.name)=='Imported Stage Password 683!'
    user=frappe.get_doc('User',target)
    user.db_set('custom_avo_contact_id','993388401')
    user.db_set('custom_avo_account','mv-centr')
    update_password(target,'StagePassword!1')
    credentials.store_new_user_password(target,'StagePassword!1')
    assert credentials.import_verified(target,'993388401','StagePassword!1')['stored']
    assert not credentials.import_verified(target,'993388401','WrongPassword!1')['stored']
    frappe.set_user(outsider)
    try:
        credentials.reveal(target)
        raise RuntimeError('outsider_read_password')
    except frappe.PermissionError:
        pass
    frappe.set_user('Administrator')
    credentials.set_credential_role(viewer,1)
    frappe.set_user(viewer)
    assert credentials.reveal(target)['password']=='StagePassword!1'
    encryption_key=frappe.conf.encryption_key
    frappe.conf.encryption_key=None
    try:
        try:
            credentials.set_new_password(target,'Stage Not Saved Password 681!')
            raise RuntimeError('missing_key_accepted')
        except frappe.ValidationError:
            pass
    finally:
        frappe.conf.encryption_key=encryption_key
    assert credentials._matches_current(target,'StagePassword!1')
    assert card.save_card('User',target,{'first_name':'Edited'})['first_name']=='Edited'
    try:
        credentials.reveal(viewer)
        raise RuntimeError('staff_password_access_allowed')
    except frappe.PermissionError:
        pass
    calls=[]
    original_sendmail=frappe.sendmail
    frappe.sendmail=lambda **kwargs:(calls.append(kwargs) or object())
    mail_ready=credentials.ensure_mail_ready
    credentials.ensure_mail_ready=lambda:None
    try:
        assert credentials.set_new_password(target,'Stage Updated Password 782!')['updated']
        assert credentials.reveal(target)['password']=='Stage Updated Password 782!'
        calls.clear()
        assert credentials.send_to_account_email(target)['queued']
        assert len(calls)==1 and calls[0]['recipients']==[target]
        assert calls[0]['redact_message_after_send'] is True
        update_password(target,'ChangedPassword!2')
        try:
            credentials.reveal(target)
            raise RuntimeError('stale_password_revealed')
        except frappe.ValidationError:
            pass
        try:
            credentials.send_to_account_email(target)
            raise RuntimeError('stale_password_sent')
        except frappe.ValidationError:
            pass
        assert len(calls)==1
        frappe.set_user('Administrator')
        staff=frappe.get_doc('User',target);staff.add_roles('Moderator')
        frappe.set_user(viewer)
        try:
            card.save_card('User',target,{'first_name':'Should not change'})
            raise RuntimeError('staff_edit_allowed')
        except frappe.PermissionError:
            pass
    finally:
        frappe.sendmail=original_sendmail
        credentials.ensure_mail_ready=mail_ready
    print(json.dumps({'source_verified':True,'unauthorized_denied':True,'role_allowed':True,
        'fixed_recipient':True,'muted_mail_blocked':True,'missing_key_blocked':True,'new_import_password':True,'new_password_works':True,'staff_account_protected':True,
        'stale_password_blocked':True,'rolled_back':True}))
finally:
    frappe.db.rollback()
    frappe.destroy()

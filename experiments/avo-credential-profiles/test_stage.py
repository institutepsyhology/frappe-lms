"""Verify profile-scoped password access on synthetic stage accounts only."""
import importlib.util
import json
import sys
import frappe
from frappe.utils.password import update_password


def load(name,path):
    spec=importlib.util.spec_from_file_location(name,path)
    module=importlib.util.module_from_spec(spec);sys.modules[name]=module;spec.loader.exec_module(module)
    return module


frappe.init(site='access-stage2.local');frappe.connect()
try:
    frappe.set_user('Administrator')
    profiles=load('lms.lms.credential_profiles','/tmp/credential_profiles.py')
    profiles.ensure_fields();frappe.db.commit();frappe.clear_cache()
    credentials=load('lms.lms.support_credentials','/tmp/credentials_profiles_support.py')
    credentials.ensure_role()
    target='profile-target-stage@example.invalid';viewer='profile-viewer-stage@example.invalid';manager='profile-manager-stage@example.invalid'
    for email in (target,viewer,manager):
        if frappe.db.exists('User',email):raise RuntimeError('synthetic_user_exists')
        user=frappe.get_doc({'doctype':'User','email':email,'first_name':'Synthetic',
            'user_type':'Website User','send_welcome_email':0}).insert(ignore_permissions=True)
    update_password(target,'Synthetic Password 812!')
    credentials.store_new_user_password(target,'Synthetic Password 812!')
    assert credentials.reveal(target)['password']=='Synthetic Password 812!'
    frappe.get_doc({'doctype':'Has Role','parent':manager,'parenttype':'User','parentfield':'roles',
                    'role':'System Manager'}).db_insert()
    frappe.clear_cache(user=manager);frappe.set_user(manager)
    assert credentials.reveal(target)['password']=='Synthetic Password 812!'
    frappe.set_user('Administrator')
    frappe.get_doc({'doctype':'Has Role','parent':viewer,'parenttype':'User','parentfield':'roles',
                    'role':'LMS Credential Manager'}).db_insert()
    frappe.clear_cache(user=viewer);frappe.set_user(viewer)
    try:
        credentials.reveal(target);raise RuntimeError('direct_role_allowed')
    except frappe.PermissionError:pass
    frappe.set_user('Administrator')
    try:
        credentials.set_credential_role(viewer,1);raise RuntimeError('individual_grant_allowed')
    except frappe.PermissionError:pass
    profile='synthetic-credential-profile-stage'
    if frappe.db.exists('Role Profile',profile):raise RuntimeError('synthetic_profile_exists')
    role_profile=frappe.get_doc({'doctype':'Role Profile','role_profile':profile});role_profile.name=profile;role_profile.db_insert()
    frappe.get_doc({'doctype':'User Role Profile','parent':viewer,'parenttype':'User',
                    'parentfield':'role_profiles','role_profile':profile}).db_insert()
    assert profiles.set_profile_access(profile,1)['enabled']
    assert frappe.db.exists('Has Role',{'parent':viewer,'parenttype':'User','role':'LMS Credential Manager'})
    frappe.set_user(viewer)
    assert credentials.reveal(target)['password']=='Synthetic Password 812!'
    try:
        profiles.set_profile_access(profile,0);raise RuntimeError('staff_can_edit_profile')
    except frappe.PermissionError:pass
    frappe.set_user('Administrator');assert not profiles.set_profile_access(profile,0)['enabled']
    frappe.set_user(viewer)
    try:
        credentials.reveal(target);raise RuntimeError('revoked_profile_allowed')
    except frappe.PermissionError:pass
    print(json.dumps({'administrator_access':True,'system_manager_access':True,'direct_role_denied':True,'individual_grant_denied':True,
        'profile_access':True,'staff_cannot_change_profile':True,'revocation_immediate':True,'rolled_back':True}))
finally:
    frappe.db.rollback();frappe.destroy()

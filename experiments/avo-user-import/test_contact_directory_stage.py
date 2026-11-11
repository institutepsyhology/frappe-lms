"""Check directory access and searching a disabled synthetic AVO user."""
import importlib.util
import json
import frappe

frappe.init(site='access-stage2.local');frappe.connect()
try:
    spec=importlib.util.spec_from_file_location('directory_api_test','/tmp/avo_api_test.py')
    api=importlib.util.module_from_spec(spec);spec.loader.exec_module(api)
    frappe.set_user('Administrator')
    role='LMS Credential Manager'
    if not frappe.db.exists('Role',role):frappe.get_doc({'doctype':'Role','role_name':role,'desk_access':0}).insert(ignore_permissions=True)
    target='directory-target-stage@example.invalid';viewer='directory-viewer-stage@example.invalid'
    for email in (target,viewer):
        if frappe.db.exists('User',email):raise RuntimeError('synthetic_user_exists')
        frappe.get_doc({'doctype':'User','email':email,'first_name':'Synthetic',
            'user_type':'Website User','send_welcome_email':0}).insert(ignore_permissions=True)
    frappe.db.set_value('User',target,{'custom_avo_contact_id':'993388421','custom_avo_account':'mv-centr','enabled':0})
    manager=frappe.get_doc('User',viewer);manager.add_roles(role)
    frappe.set_user(viewer)
    assert any(row.name==target for row in api.get_members(search='993388421',status='All'))
    assert not any(row.name==target for row in api.get_members(search='993388421',status='Active'))
    assert api.get_member(target).name==target
    try:
        api.save_role(target,'Moderator',1)
        raise RuntimeError('credential_manager_granted_role')
    except frappe.PermissionError:
        pass
    print(json.dumps({'search_id':True,'disabled_filter':True,'credential_role_can_search':True,
        'role_escalation_denied':True,'rolled_back':True}))
finally:
    frappe.db.rollback();frappe.destroy()

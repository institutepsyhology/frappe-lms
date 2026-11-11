"""Verify moderator access on isolated synthetic records, with rollback."""
import importlib.util
import json
import frappe

frappe.init(site='access-stage2.local');frappe.connect()
try:
    frappe.set_user('Administrator')
    spec=importlib.util.spec_from_file_location('access_actions_stage','/tmp/moderator_access_actions.py')
    actions=importlib.util.module_from_spec(spec);spec.loader.exec_module(actions)
    moderator='synthetic-access-moderator@example.invalid';student='synthetic-access-student@example.invalid'
    for email in (moderator,student):
        if frappe.db.exists('User',email):raise RuntimeError('test_user_exists')
        frappe.get_doc({'doctype':'User','email':email,'first_name':'Synthetic','user_type':'Website User','send_welcome_email':0}).insert(ignore_permissions=True)
    frappe.get_doc('User',moderator).add_roles('Moderator')
    course=frappe.get_doc({'doctype':'LMS Course','title':'Synthetic moderator access',
        'short_introduction':'Synthetic','description':'Synthetic','published':0,'disable_self_learning':1,
        'instructors':[{'instructor':moderator}]}).insert(ignore_permissions=True)
    frappe.set_user(moderator)
    assert not frappe.has_permission('LMS Access Policy','create')
    assert not frappe.has_permission('LMS Access Grant','write')
    assert actions.get_course_access_overview(course.name)['policy_exists'] is False
    assert actions.create_course_access_policy(course.name)['enabled'] is False
    overview=actions.get_course_access_overview(course.name)
    assert overview['policy_exists'] and not overview['policy_enabled']
    values={'default_personal_end_type':'Unlimited','default_personal_end_at':None,'default_personal_end_days':0,
        'global_end_type':'Unlimited','global_end_at':None,'completed_retention_type':'None','completed_retention_days':0}
    assert not actions.update_course_access_defaults(course.name,values)['enabled']
    frappe.set_user('Administrator')
    grant=frappe.get_doc({'doctype':'LMS Access Grant','course':course.name,'member':student,'status':'Draft',
        'personal_end_type':'Unlimited','course_end_type':'Inherit'}).insert(ignore_permissions=True)
    frappe.set_user(moderator)
    assert actions.update_grant_timing(grant.name,'2026-11-11 10:00:00','Unlimited',None,0,False)['status']=='Draft'
    assert actions.get_grant_lessons(grant.name)==[]
    try:
        actions.reset_learning_records('fake',{},'');raise RuntimeError('moderator_reset_allowed')
    except frappe.PermissionError:pass
    frappe.set_user(student)
    try:
        actions.get_course_access_overview(course.name);raise RuntimeError('student_access_allowed')
    except frappe.PermissionError:pass
    print(json.dumps({'moderator_reads_and_updates':True,'grant_timing_updated':True,'direct_crud_denied':True,'no_auto_enable':True,
                      'destructive_reset_denied':True,'student_denied':True,'rolled_back':True}))
finally:
    frappe.db.rollback();frappe.destroy()

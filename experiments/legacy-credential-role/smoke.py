"""Exercise legacy-role migration on synthetic isolated-stage users only."""
import uuid
import frappe


def run():
    if frappe.local.site!='access-stage2.local':
        raise RuntimeError('isolated_stage_required')
    from lms.lms.staff_positions import save_employee,save_position
    from lms.lms.staff_policy import clear_policy_cache,has_capability
    from lms.lms.support_credentials import ensure_role
    previous=frappe.session.user
    prefix='legacy-credential-smoke-'+uuid.uuid4().hex[:8]
    report={}
    try:
        frappe.set_user('Administrator');clear_policy_cache();ensure_role()
        users=[]
        for suffix,extra in (('reader',[]),('plain',[]),('system',['System Manager'])):
            user=frappe.get_doc({'doctype':'User','email':prefix+'-'+suffix+'@example.invalid',
                'first_name':prefix+'-'+suffix,'send_welcome_email':0,'user_type':'System User' if extra else 'Website User',
                'roles':[{'role':r} for r in ['LMS Student','Moderator','Course Creator','LMS Credential Manager',*extra]]}).insert(ignore_permissions=True)
            users.append(user.name)
        # Real Role Profile preservation: saving User unnecessarily would
        # re-project this profile. Position attachment must leave it untouched.
        profile=frappe.get_doc({'doctype':'Role Profile','role_profile':prefix+'-system-profile',
            'roles':[{'role':r} for r in ('System Manager','LMS Student','Moderator')]}).insert(ignore_permissions=True)
        technical=frappe.get_doc('User',users[2])
        technical.set('role_profiles',[{'role_profile':profile.name}]);technical.save(ignore_permissions=True)
        technical=frappe.get_doc('User',users[2])
        technical_before=([row.role for row in technical.roles],
            [row.role_profile for row in technical.role_profiles],technical.modified,technical.user_type)
        positions=[]
        for credential in (True,False):
            rights=[{'resource':'contacts','action':'read'}]
            if credential:rights.append({'resource':'credentials','action':'read'})
            position=save_position({'title':prefix+('-read' if credential else '-plain'),
                'active':1,'course_scope':'All','native_roles':['LMS Student'],'permissions':rights})
            positions.append(position['name'])
        for member,position in zip(users[:2],positions):
            save_employee(member,position)
            roles=set(frappe.get_all('Has Role',filters={'parent':member,'parenttype':'User'},pluck='role'))
            if roles!={'LMS Student'}:
                raise RuntimeError('legacy_role_projection_failed')
        report['legacy_marker_removed']=True
        report['only_selected_native_roles']=True
        for member,expected in zip(users[:2],(True,False)):
            frappe.set_user(member);clear_policy_cache()
            if has_capability('credentials','read') is not expected:
                raise RuntimeError('position_credential_policy_failed')
        report['credential_permission_comes_from_position']=True
        frappe.set_user('Administrator');clear_policy_cache()
        save_employee(users[2],positions[0])
        technical=frappe.get_doc('User',users[2])
        report['system_roles_preserved']=[row.role for row in technical.roles]==technical_before[0]
        report['system_role_profiles_preserved']=[row.role_profile for row in technical.role_profiles]==technical_before[1]
        report['system_user_not_rewritten']=technical.modified==technical_before[2] and technical.user_type==technical_before[3]
        report['system_position_assignment_saved']=bool(frappe.db.exists('LMS Staff Assignment',{'user':users[2]}))
        report['users_preserved']=all(frappe.db.exists('User',user) for user in users)
        if not all(report.values()):
            raise RuntimeError('legacy_smoke_failed')
        return report
    finally:
        frappe.db.rollback();frappe.set_user(previous);clear_policy_cache()

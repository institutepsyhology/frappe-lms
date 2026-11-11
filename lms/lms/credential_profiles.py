"""Password access is granted by staff role profiles, never a personal toggle."""
import frappe
from frappe import _
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

FIELD = 'custom_can_manage_credentials'


def ensure_fields():
    create_custom_fields({'Role Profile': [{
        'fieldname': FIELD, 'label': 'Доступ к паролям контактов', 'fieldtype': 'Check',
        'insert_after': 'role_profile', 'default': '0', 'no_copy': 1, 'permlevel': 1,
    }]}, update=True)


def can_manage_credentials(user=None):
    user = user or frappe.session.user
    if not user or user == 'Guest':
        return False
    if user == 'Administrator' or 'System Manager' in frappe.get_roles(user):
        return True
    if not frappe.get_meta('Role Profile').has_field(FIELD):
        return False
    # Query current profile membership on each request: removing a right takes
    # effect immediately, even before Frappe refreshes cached user roles.
    return bool(frappe.db.sql('''select 1 from `tabRole Profile` p
        join `tabUser Role Profile` urp on urp.role_profile=p.name
        where p.custom_can_manage_credentials=1 and urp.parent=%s
        and urp.parenttype='User' and urp.parentfield='role_profiles' limit 1''', (user,)))


@frappe.whitelist()
def list_profiles():
    frappe.only_for('System Manager')
    return frappe.get_all('Role Profile', fields=['name', 'role_profile', FIELD], order_by='name', limit_page_length=0)


@frappe.whitelist(methods=['POST'])
def set_profile_access(profile, enabled):
    frappe.only_for('System Manager')
    if not isinstance(profile,str) or not frappe.db.exists('Role Profile',profile):
        frappe.throw(_('Invalid role profile.'),frappe.ValidationError)
    if type(enabled) not in (bool,int,str) or enabled not in (0,1,'0','1',False,True):
        frappe.throw(_('Invalid permission value.'),frappe.ValidationError)
    value=int(str(enabled) in ('1','True'))
    # Do not save the Role Profile: its on_update can rewrite employees' roles.
    frappe.db.set_value('Role Profile',profile,FIELD,value)
    frappe.logger('lms_credentials').info({'action':'profile_permission_changed','actor':frappe.session.user,'profile':profile,'enabled':value})
    return {'enabled':bool(value)}

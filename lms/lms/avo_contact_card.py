"""Administrator contact card for LMS users and AVO-only contacts.

Only explicit profile fields are exposed. Credentials, reset tokens, and
unmigrated AVO activity are never returned by these methods.
"""
import json

import frappe
from frappe import _


SOCIAL_FIELDS = (
    'custom_avo_telegram_id', 'custom_avo_telegram_username',
    'custom_avo_vk_id', 'custom_avo_vk_username',
)
IDENTITY_FIELDS = ('custom_avo_contact_id', 'custom_avo_account')
EDITABLE = ('first_name', 'middle_name', 'last_name', 'mobile_no') + SOCIAL_FIELDS
SITE_ACCOUNTS = {'my-lk.mv-centr.ru':'mv-centr', 'access-stage2.local':'mv-centr',
                 'my-lk.iomp.ru':'iomp', 'my-lk.mastervision.su':'mastervision'}


def _check_access():
    frappe.only_for(['System Manager', 'LMS Credential Manager'])


def _document(kind, name):
    if kind not in ('User', 'Contact') or not isinstance(name, str) or not name.strip():
        frappe.throw(_('Invalid contact.'), frappe.ValidationError)
    if kind == 'User' and name in ('Administrator', 'Guest'):
        frappe.throw(_('This account cannot be managed here.'), frappe.PermissionError)
    return frappe.get_doc(kind, name)


def _present(doc):
    meta = frappe.get_meta(doc.doctype)
    value = lambda field: doc.get(field) if meta.has_field(field) else None
    result = {'kind':doc.doctype, 'name':doc.name, 'first_name':value('first_name') or '',
              'middle_name':value('middle_name') or '', 'last_name':value('last_name') or '',
              'email':value('email') if doc.doctype == 'User' else value('email_id'),
              'mobile_no':value('mobile_no') or '', 'enabled':bool(value('enabled')) if doc.doctype == 'User' else None,
              'created':str(doc.creation) if doc.creation else None,
              'credential_manager': bool(doc.doctype == 'User' and frappe.db.exists('Has Role',
                  {'parent':doc.name,'parenttype':'User','role':'LMS Credential Manager'}))}
    for field in IDENTITY_FIELDS + SOCIAL_FIELDS:
        result[field] = value(field) or ''
    result['custom_no_marketing_email'] = bool(value('custom_no_marketing_email'))
    return result


@frappe.whitelist()
def get_card(kind, name):
    _check_access()
    return _present(_document(kind, name))


@frappe.whitelist()
def list_source_contacts(start=0, search=None):
    """Page imported contacts that have no linked User account."""
    _check_access()
    try:
        start = int(start)
    except (TypeError,ValueError):
        frappe.throw(_('Invalid offset.'), frappe.ValidationError)
    if start < 0 or (search is not None and (not isinstance(search,str) or len(search)>140)):
        frappe.throw(_('Invalid search.'), frappe.ValidationError)
    if not frappe.get_meta('Contact').has_field('custom_avo_contact_id'):
        return []
    account = SITE_ACCOUNTS.get(frappe.local.site)
    if not account:
        frappe.throw(_('Unknown AVO account.'), frappe.ValidationError)
    filters = [['custom_avo_contact_id','is','set'], ['user','is','not set'], ['custom_avo_account','=',account]]
    or_filters = {}
    if search:
        term = '%' + search.strip() + '%'
        or_filters = {field:['like',term] for field in ('full_name','email_id','mobile_no','custom_avo_contact_id')}
    rows = frappe.get_all('Contact', filters=filters, or_filters=or_filters,
        fields=['name','full_name','email_id','custom_avo_contact_id'], order_by='modified desc',
        start=start, page_length=13)
    return [{'name':row.name, 'full_name':row.full_name, 'username':'', 'roles':[],
             'email':row.email_id, 'avo_id':row.custom_avo_contact_id, 'kind':'Contact'} for row in rows]


@frappe.whitelist(methods=['POST'])
def save_card(kind, name, values):
    _check_access()
    doc = _document(kind, name)
    if kind == 'User' and frappe.session.user != 'Administrator' and 'System Manager' not in frappe.get_roles():
        from lms.lms.support_credentials import PRIVILEGED_ROLES
        if doc.user_type == 'System User' or PRIVILEGED_ROLES.intersection(frappe.get_roles(doc.name)):
            frappe.throw(_('Only a system manager can edit a staff account.'), frappe.PermissionError)
    if isinstance(values, str):
        values = json.loads(values)
    allowed = set(EDITABLE) | {'custom_no_marketing_email'} | ({'email'} if kind == 'Contact' else set())
    if not isinstance(values, dict) or set(values) - allowed:
        frappe.throw(_('Invalid contact fields.'), frappe.ValidationError)
    meta = frappe.get_meta(kind)
    for field, value in values.items():
        if field == 'custom_no_marketing_email':
            if type(value) not in (bool, int) or value not in (0, 1):
                frappe.throw(_('Invalid marketing preference.'), frappe.ValidationError)
            doc.set(field, int(value))
            continue
        if not isinstance(value, str) or len(value) > 140 or (field != 'email' and not meta.has_field(field)):
            frappe.throw(_('Invalid contact field.'), frappe.ValidationError)
        if kind == 'Contact' and field == 'email':
            from frappe.utils import validate_email_address
            email = value.strip()
            if email and not validate_email_address(email, throw=False):
                frappe.throw(_('Enter a valid email address.'), frappe.ValidationError)
            selected = next((row for row in doc.email_ids if row.is_primary), None)
            if selected:
                if email: selected.email_id = email
                else: doc.remove(selected)
            elif email:
                doc.append('email_ids', {'email_id':email, 'is_primary':1})
        elif kind == 'Contact' and field == 'mobile_no':
            # Contact.mobile_no is derived from its child phone table.
            selected = next((row for row in doc.phone_nos if row.is_primary_mobile_no), None)
            if selected:
                if value.strip(): selected.phone = value.strip()
                else: doc.remove(selected)
            elif value.strip():
                doc.append('phone_nos', {'phone':value.strip(), 'is_primary_mobile_no':1})
        else:
            doc.set(field, value.strip())
    if not doc.first_name and not doc.last_name:
        frappe.throw(_('Enter a first or last name.'), frappe.ValidationError)
    doc.save(ignore_permissions=True)
    if doc.get('custom_no_marketing_email') and doc.get('custom_avo_account') and doc.get('custom_avo_contact_id'):
        from lms.lms.avo_marketing import protect_existing_groups
        protect_existing_groups(doc.custom_avo_account, [doc.custom_avo_contact_id])
    return _present(doc)


@frappe.whitelist()
def courses_for_user(name):
    _check_access()
    _document('User', name)
    enrollments = frappe.get_all('LMS Enrollment', filters={'member':name},
        fields=['course', 'creation', 'progress'], order_by='creation desc', limit_page_length=200)
    courses = {row.name:row for row in frappe.get_all('LMS Course',
        filters={'name':['in', [e.course for e in enrollments]]}, fields=['name','title'], limit_page_length=0)} if enrollments else {}
    grants = frappe.get_all('LMS Access Grant', filters={'member':name},
        fields=['course','status','starts_at','ends_at'], order_by='creation desc', limit_page_length=0)
    return [{'course':e.course, 'title':courses[e.course].title if e.course in courses else e.course,
             'enrolled_at':e.creation, 'progress':e.progress,
             'grants':[g for g in grants if g.course == e.course]} for e in enrollments]


@frappe.whitelist(methods=['POST'])
def send_password_reset(name):
    _check_access()
    user = _document('User', name)
    if not user.enabled or not user.email:
        frappe.throw(_('This account has no active email login.'), frappe.ValidationError)
    from lms.lms.support_credentials import ensure_mail_ready
    ensure_mail_ready()
    user.validate_reset_password()
    user._reset_password(send_email=True)
    return {'queued':True}


@frappe.whitelist(methods=['POST'])
def set_account_enabled(name, enabled):
    frappe.only_for('System Manager')
    user = _document('User', name)
    if name == frappe.session.user or enabled not in (0,1,'0','1',False,True):
        frappe.throw(_('This account cannot be changed here.'), frappe.ValidationError)
    user.enabled = int(str(enabled) in ('1','True'))
    user.save(ignore_permissions=True)
    return {'enabled':bool(user.enabled)}


@frappe.whitelist(methods=['POST'])
def change_user_email(name, email):
    """Rename the User through Frappe so linked documents follow the login."""
    from frappe.utils import validate_email_address
    frappe.only_for('System Manager')
    user = _document('User', name)
    if name == frappe.session.user:
        frappe.throw(_('Change your own login from another administrator account.'), frappe.ValidationError)
    if not isinstance(email,str) or len(email)>140 or not validate_email_address(email.strip(),throw=False):
        frappe.throw(_('Enter a valid email address.'), frappe.ValidationError)
    email=email.strip().lower()
    if email==user.name:
        return {'name':user.name}
    if frappe.db.exists('User',email):
        frappe.throw(_('An account with this email already exists.'), frappe.DuplicateEntryError)
    renamed=frappe.rename_doc('User',user.name,email,merge=False,show_alert=False,rebuild_search=False)
    return {'name':renamed}

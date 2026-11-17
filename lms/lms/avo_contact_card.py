"""Administrator contact card for LMS users and AVO-only contacts.

Only explicit profile fields are exposed. Credentials, reset tokens, and
unmigrated AVO activity are never returned by these methods.
"""
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
    from lms.lms.staff_authority import require_capability
    require_capability('contacts', 'read')


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
              'email':value('email') if doc.doctype == 'User' else value('email_id') or value('custom_avo_source_email'),
              'mobile_no':value('mobile_no') or '', 'enabled':bool(value('enabled')) if doc.doctype == 'User' else None,
              'created':str(doc.creation) if doc.creation else None}
    for field in IDENTITY_FIELDS + SOCIAL_FIELDS:
        result[field] = value(field) or ''
    result['custom_no_marketing_email'] = bool(value('custom_no_marketing_email'))
    return result


@frappe.whitelist()
def get_card(kind, name):
    from lms.lms.contact_workspace import get_card as workspace_get_card
    return workspace_get_card(kind, name)


@frappe.whitelist()
def resolve_source_id(source_id):
    from lms.lms.contact_workspace import resolve_source_id as workspace_resolve
    return workspace_resolve(source_id)


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
    from lms.lms.contact_workspace import save_card as workspace_save_card
    return workspace_save_card(kind, name, values)


@frappe.whitelist()
def courses_for_user(name):
    from lms.lms.contact_workspace import list_person_courses
    return list_person_courses('User', name, page=1, page_size=200)['rows']


@frappe.whitelist(methods=['POST'])
def send_password_reset(name):
    from lms.lms.staff_authority import require_capability
    from lms.lms.support_credentials import _support_target
    from lms.lms.contact_workspace import _scoped
    require_capability('credentials', 'send')
    user = _scoped(_support_target(name))
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
    from lms.lms.staff_authority import require_capability
    from lms.lms.contact_workspace import _identity
    require_capability('contacts', 'write')
    user, _ = _identity('User', name)
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
    from lms.lms.staff_authority import require_capability
    from lms.lms.contact_workspace import _identity
    require_capability('contacts', 'write')
    user, _ = _identity('User', name)
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

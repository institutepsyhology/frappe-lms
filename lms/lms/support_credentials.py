"""Role-scoped, encrypted support passwords for LMS accounts.

The recoverable copy is a separate encrypted __Auth value, never a User field.
It is disclosed only when it still matches the current login hash.
"""
import frappe
from frappe import _
from frappe.utils import escape_html
from frappe.utils.password import get_decrypted_password, passlibctx, set_encrypted_password

ROLE = 'LMS Credential Manager'
FIELD = 'lms_support_password'
PRIVILEGED_ROLES = {'System Manager','Moderator','Course Creator','Batch Evaluator',ROLE}


def ensure_role():
    if not frappe.db.exists('Role', ROLE):
        frappe.get_doc({'doctype':'Role','role_name':ROLE,'desk_access':0}).insert(ignore_permissions=True)


def _authorized():
    frappe.only_for(ROLE)


def _user(name):
    if not isinstance(name, str) or not name or name in ('Administrator','Guest'):
        frappe.throw(_('Invalid account.'), frappe.ValidationError)
    return frappe.get_doc('User',name)


def _support_target(name):
    user=_user(name)
    actor_roles=set(frappe.get_roles())
    target_roles=set(frappe.get_roles(user.name))
    if (frappe.session.user != 'Administrator' and 'System Manager' not in actor_roles and
        (user.user_type == 'System User' or bool(PRIVILEGED_ROLES & target_roles))):
        frappe.throw(_('Only a system manager can manage a staff account password.'), frappe.PermissionError)
    return user


def _matches_current(name, password, lock=False):
    suffix = ' FOR UPDATE' if lock else ''
    rows = frappe.db.sql("SELECT password FROM `__Auth` WHERE doctype=%s AND name=%s AND fieldname=%s AND encrypted=0" + suffix,
                         ('User',name,'password'))
    if not rows or not isinstance(password,str) or not password:
        return False
    try:
        return bool(passlibctx.verify(password,rows[0][0]))
    except (ValueError, TypeError):
        return False


def _ensure_crypto_ready():
    # Never let parallel requests create different first-use site keys.
    if not frappe.conf.get('encryption_key'):
        frappe.throw(_('Password encryption is not configured on this site.'), frappe.ValidationError)


def _current_password(name, lock=False):
    _ensure_crypto_ready()
    value = get_decrypted_password('User',name,FIELD,raise_exception=False)
    if not value or not _matches_current(name,value,lock=lock):
        frappe.throw(_('The current password is unavailable. Set a new password or send a reset link.'), frappe.ValidationError)
    return value


def store_new_user_password(name, password):
    """Save the encrypted support copy inside the same creation transaction."""
    _ensure_crypto_ready()
    if not _matches_current(name,password,lock=True):
        frappe.throw(_('New account password could not be verified.'), frappe.ValidationError)
    set_encrypted_password('User',name,password,FIELD)


def _audit(action, name):
    frappe.logger('lms_credentials').info({'action':action,'actor':frappe.session.user,'user':name})


def ensure_mail_ready():
    from frappe.email.doctype.email_account.email_account import EmailAccount, are_emails_muted
    if are_emails_muted():
        frappe.throw(_('Outgoing email is disabled on this site.'), frappe.ValidationError)
    account=EmailAccount.find_default_outgoing()
    if not account or account.get('awaiting_password'):
        frappe.throw(_('Configure an outgoing email account first.'), frappe.ValidationError)


@frappe.whitelist(methods=['POST'])
def import_verified(name, source_id, password):
    """Store an AVO snapshot password only if it is the current login password."""
    if frappe.session.user != 'Administrator' or frappe.local.site not in ('my-lk.mv-centr.ru','access-stage2.local'):
        frappe.throw(_('Administrator required.'), frappe.PermissionError)
    user = _user(name)
    if (not isinstance(source_id,str) or not source_id.isdigit() or
        user.get('custom_avo_contact_id') != source_id or user.get('custom_avo_account') != 'mv-centr'):
        frappe.throw(_('Source identity mismatch.'), frappe.ValidationError)
    _ensure_crypto_ready()
    if not _matches_current(user.name,password,lock=True):
        return {'stored':False,'reason':'password_mismatch'}
    set_encrypted_password('User',user.name,password,FIELD)
    return {'stored':True}


@frappe.whitelist(methods=['POST'])
def reveal(name):
    _authorized()
    user=_support_target(name)
    password=_current_password(user.name)
    _audit('reveal',user.name)
    return {'password':password}


@frappe.whitelist(methods=['POST'])
def send_to_account_email(name):
    _authorized()
    user=_support_target(name)
    if not user.enabled or not user.email:
        frappe.throw(_('This account has no active email login.'), frappe.ValidationError)
    ensure_mail_ready()
    password=_current_password(user.name,lock=True)
    queued=frappe.sendmail(recipients=[user.email], subject=_('Your personal account access'),
        message=_('Your login: {0}<br>Your password: {1}').format(escape_html(user.email),escape_html(password)),
        now=False, add_unsubscribe_link=0, redact_message_after_send=True)
    if not queued:
        frappe.throw(_('The message could not be queued.'), frappe.ValidationError)
    _audit('send_password',user.name)
    return {'queued':True}


@frappe.whitelist(methods=['POST'])
def set_new_password(name, password):
    _authorized()
    user=_support_target(name)
    if not user.enabled or not isinstance(password,str) or not password or len(password)>512:
        frappe.throw(_('Enter a valid new password for an active account.'), frappe.ValidationError)
    _ensure_crypto_ready()
    user.new_password=password
    user.save(ignore_permissions=True)
    store_new_user_password(user.name,password)
    _audit('set_password',user.name)
    return {'updated':True}


@frappe.whitelist(methods=['POST'])
def set_credential_role(name, enabled):
    frappe.only_for('System Manager')
    user=_user(name)
    if enabled not in (0,1,'0','1',False,True):
        frappe.throw(_('Invalid role value.'),frappe.ValidationError)
    enabled = str(enabled) in ('1','True')
    if enabled:
        user.add_roles(ROLE)
    else:
        user.remove_roles(ROLE)
    _audit('grant_role' if enabled else 'revoke_role',user.name)
    return {'enabled':enabled}

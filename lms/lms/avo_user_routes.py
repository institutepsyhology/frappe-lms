"""Account-scoped numeric identifiers for LMS user routes."""
import frappe
from frappe import _
from lms.lms.avo_contact_card import SITE_ACCOUNTS


def _account():
    return SITE_ACCOUNTS.get(frappe.local.site)


def _id(value):
    return isinstance(value, str) and value.isascii() and value.isdigit() and not value.startswith('0') and len(value) <= 20


@frappe.whitelist()
def get_members(start: int = 0, search: str = None, role: str = 'All', status: str = 'Active'):
    from lms.lms.api import get_members as original
    rows = original(start, search, role, status)
    account = _account()
    if not account or not rows or not frappe.get_meta('User').has_field('custom_avo_contact_id'):
        return rows
    ids = frappe.get_all('User', filters={'name': ['in', [row.name for row in rows]], 'custom_avo_account': account},
        fields=['name', 'custom_avo_contact_id'], limit_page_length=len(rows))
    by_name = {row.name: row.custom_avo_contact_id for row in ids if _id(row.custom_avo_contact_id)}
    for row in rows:
        row['custom_avo_contact_id'] = by_name.get(row.name)
    return rows


@frappe.whitelist()
def resolve_member(source_id: str):
    from lms.lms.staff_policy import require_capability
    require_capability('contacts', 'read')
    if not _id(source_id) or not _account():
        frappe.throw(_('Invalid contact ID.'), frappe.ValidationError)
    rows = frappe.get_all('User', filters={'custom_avo_account': _account(), 'custom_avo_contact_id': source_id},
                          fields=['name'], limit_page_length=2)
    contacts = frappe.get_all('Contact', filters={'custom_avo_account': _account(), 'custom_avo_contact_id': source_id},
                              fields=['user'], limit_page_length=2)
    if len(rows) != 1 or len(contacts) > 1 or any(c.user != rows[0].name for c in contacts):
        frappe.throw(_('Contact ID not found or is ambiguous.'), frappe.ValidationError)
    return {'kind': 'User', 'name': rows[0].name}


@frappe.whitelist()
def get_profile_details(username: str):
    from lms.lms.api import get_profile_details as original
    identifier = username
    if _id(username) and _account():
        rows = frappe.get_all('User', filters={'custom_avo_account': _account(), 'custom_avo_contact_id': username},
                              fields=['name', 'username'], limit_page_length=2)
        legacy = frappe.db.get_value('User', {'username': username}, 'name')
        if len(rows) > 1 or (rows and legacy and legacy != rows[0].name):
            frappe.throw(_('User identifier is ambiguous.'), frappe.ValidationError)
        if rows:
            identifier = rows[0].username
    details = original(identifier)
    if _account() and frappe.get_meta('User').has_field('custom_avo_contact_id'):
        identity = frappe.db.get_value('User', details.name, ['custom_avo_account', 'custom_avo_contact_id'], as_dict=True)
        if identity and identity.custom_avo_account == _account() and _id(identity.custom_avo_contact_id):
            details['avo_route_id'] = identity.custom_avo_contact_id
    return details

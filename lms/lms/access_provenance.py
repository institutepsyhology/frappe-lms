"""Immutable, explicitly recorded issuance metadata; never infer old events."""
import frappe
from frappe import _
from frappe.utils import get_datetime, now_datetime

FIELDS = ('access_source', 'issued_by', 'issued_at', 'source_reference')


def validate(doc):
    source = doc.get('access_source') or 'Unknown'
    if source not in ('Unknown', 'Manual', 'Import', 'Purchase'):
        frappe.throw(_('Invalid access source.'), frappe.ValidationError)
    doc.access_source = source
    previous = None if doc.is_new() else doc.get_doc_before_save()
    if previous:
        for field in FIELDS:
            old = previous.get(field) or ('Unknown' if field == 'access_source' else None)
            value = doc.get(field) or ('Unknown' if field == 'access_source' else None)
            if field == 'issued_at':
                old = get_datetime(old) if old else None
                value = get_datetime(value) if value else None
            if old != value:
                frappe.throw(_('The original access issuance record cannot be changed.'), frappe.ValidationError)
        return
    if source == 'Unknown':
        if any(doc.get(field) for field in FIELDS[1:]):
            frappe.throw(_('Unknown access must not include an invented issuer or event.'), frappe.ValidationError)
        return
    if source == 'Manual':
        from lms.lms.staff_authority import require_capability
        require_capability('course_access', 'create', course=doc.course)
    elif frappe.session.user != 'Administrator':
        # Imports/payment integrations need an authenticated server-side event;
        # clients cannot label arbitrary access as a purchase or migration.
        frappe.throw(_('Administrator required for this access source.'), frappe.PermissionError)
    doc.issued_by = frappe.session.user
    doc.issued_at = now_datetime()

"""Additive schema setup, shared by the isolated preflight and guarded release."""
import frappe

DOCTYPES = (
    'lms_staff_position_permission', 'lms_staff_position', 'lms_staff_assignment',
    'lms_access_block', 'lms_access_grant', 'lms_enrollment',
)


def apply_schema():
    site = frappe.local.site
    if site not in ('my-lk.mv-centr.ru', 'my-lk.mastervision.su', 'my-lk.iomp.ru', 'access-stage2.local'):
        raise RuntimeError('unexpected_site')
    if not frappe.conf.get('encryption_key'):
        raise RuntimeError('existing_encryption_key_required')
    for doctype in DOCTYPES:
        frappe.reload_doc('lms', 'doctype', doctype, force=True)
    for doctype in ('LMS Access Grant', 'LMS Enrollment'):
        if not all(frappe.get_meta(doctype).has_field(name) for name in
                   ('access_source', 'issued_by', 'issued_at', 'source_reference')):
            raise RuntimeError('issuance_schema_incomplete')
    if not all(frappe.db.table_exists(doctype) for doctype in
               ('LMS Staff Position', 'LMS Staff Assignment', 'LMS Staff Position Permission', 'LMS Access Block')):
        raise RuntimeError('staff_schema_incomplete')
    frappe.db.commit()
    frappe.clear_cache()
    from frappe import translate
    translate.clear_cache()
    return {'site': site, 'additive_schema_verified': True, 'positions_auto_assigned': False}

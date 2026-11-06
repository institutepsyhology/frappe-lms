"""Widen only LMS title fields to 512; run after verified site backups.

An existing non-matching property setter is never replaced. Widening is
idempotent and does not rename documents or rewrite course and lesson titles.
"""
import frappe

SITES = {'my-lk.mv-centr.ru','my-lk.mastervision.su','my-lk.iomp.ru'}
DOCTYPES = ('LMS Course','Course Lesson')


def _set_length(doctype):
    from frappe.custom.doctype.property_setter.property_setter import make_property_setter
    make_property_setter(doctype,'title','length',512,'Int')


def execute():
    if frappe.local.site not in SITES:
        raise ValueError('unexpected_site')
    for doctype in DOCTYPES:
        rows=frappe.get_all('Property Setter',filters={'doc_type':doctype,'field_name':'title','property':'length'},fields=['name','value'],limit_page_length=2)
        if len(rows)>1 or (rows and str(rows[0].value)!='512'):
            raise ValueError('conflicting_title_length_setting')
        field=frappe.get_meta(doctype,cached=False).get_field('title')
        if not field or field.fieldtype!='Data' or int(field.length or 140)>512:
            raise ValueError('unexpected_title_schema')
    for doctype in DOCTYPES:
        if not frappe.db.exists('Property Setter',{'doc_type':doctype,'field_name':'title','property':'length'}):
            _set_length(doctype)
        frappe.db.commit()
        frappe.clear_cache(doctype=doctype)
        frappe.db.updatedb(doctype)
        frappe.clear_cache(doctype=doctype)
        field=frappe.get_meta(doctype,cached=False).get_field('title')
        if int(field.length or 140)!=512:
            raise ValueError('title_metadata_not_updated')
        cols=frappe.db.sql('SHOW COLUMNS FROM `tab'+doctype+'` LIKE %s',('title',),as_dict=True)
        if len(cols)!=1 or cols[0]['Type'].lower()!='varchar(512)':
            raise ValueError('title_column_not_updated')
    frappe.db.commit()

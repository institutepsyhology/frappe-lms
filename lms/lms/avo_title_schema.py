"""Widen only LMS title fields to 512; run after verified site backups.

An existing non-matching property setter is never replaced. Widening is
idempotent and does not rename documents or rewrite course and lesson titles.
"""
import frappe

SITES = {'my-lk.mv-centr.ru','my-lk.mastervision.su','my-lk.iomp.ru'}
FIELDS = (('LMS Course','title'),('Course Lesson','title'),
          ('Course Chapter','course_title'),('Batch Course','title'),
          ('LMS Certificate Request','course_title'),('LMS Certificate','course_title'),
          ('LMS Program Course','course_title'),('Scheduled Flow','lesson_title'))


def _set_length(doctype,fieldname):
    from frappe.custom.doctype.property_setter.property_setter import make_property_setter
    make_property_setter(doctype,fieldname,'length',512,'Int')


def execute():
    if frappe.local.site not in SITES:
        raise ValueError('unexpected_site')
    for doctype,fieldname in FIELDS:
        rows=frappe.get_all('Property Setter',filters={'doc_type':doctype,'field_name':fieldname,'property':'length'},fields=['name','value'],limit_page_length=2)
        if len(rows)>1 or (rows and str(rows[0].value)!='512'):
            raise ValueError('conflicting_title_length_setting')
        field=frappe.get_meta(doctype,cached=False).get_field(fieldname)
        if not field or field.fieldtype!='Data' or int(field.length or 140)>512:
            raise ValueError('unexpected_title_schema')
    for doctype,fieldname in FIELDS:
        if not frappe.db.exists('Property Setter',{'doc_type':doctype,'field_name':fieldname,'property':'length'}):
            _set_length(doctype,fieldname)
        frappe.db.commit()
        frappe.clear_cache(doctype=doctype)
        frappe.db.updatedb(doctype)
        frappe.clear_cache(doctype=doctype)
        field=frappe.get_meta(doctype,cached=False).get_field(fieldname)
        if int(field.length or 140)!=512:
            raise ValueError('title_metadata_not_updated')
        cols=frappe.db.sql('SHOW COLUMNS FROM `tab'+doctype+'` LIKE %s',(fieldname,),as_dict=True)
        if len(cols)!=1 or cols[0]['Type'].lower()!='varchar(512)':
            raise ValueError('title_column_not_updated')
    frappe.db.commit()

"""Widen lesson content without changing any stored lesson text."""
import frappe

SITES={'my-lk.mv-centr.ru','my-lk.mastervision.su','my-lk.iomp.ru'}


def _set_long_text():
    from frappe.custom.doctype.property_setter.property_setter import make_property_setter
    make_property_setter('Course Lesson','content','fieldtype','Long Text','Select')


def execute():
    if frappe.local.site not in SITES:
        raise ValueError('unexpected_site')
    setters=frappe.get_all('Property Setter',filters={'doc_type':'Course Lesson','field_name':'content','property':'fieldtype'},fields=['name','value'],limit_page_length=2)
    if len(setters)>1 or (setters and setters[0].value!='Long Text'):
        raise ValueError('conflicting_content_field_setting')
    field=frappe.get_meta('Course Lesson',cached=False).get_field('content')
    if not field or field.fieldtype not in ('Text','Long Text'):
        raise ValueError('unexpected_content_field_schema')
    column=frappe.db.sql('SELECT DATA_TYPE FROM information_schema.COLUMNS WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME=%s AND COLUMN_NAME=%s',('tabCourse Lesson','content'))
    if len(column)!=1 or column[0][0].lower() not in ('text','longtext'):
        raise ValueError('unexpected_content_column_schema')
    if not setters:
        _set_long_text()
    frappe.db.commit()
    frappe.clear_cache(doctype='Course Lesson')
    frappe.db.updatedb('Course Lesson')
    frappe.clear_cache(doctype='Course Lesson')
    field=frappe.get_meta('Course Lesson',cached=False).get_field('content')
    column=frappe.db.sql('SELECT DATA_TYPE FROM information_schema.COLUMNS WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME=%s AND COLUMN_NAME=%s',('tabCourse Lesson','content'))
    if not field or field.fieldtype!='Long Text' or len(column)!=1 or column[0][0].lower()!='longtext':
        raise ValueError('content_schema_not_updated')
    frappe.db.commit()

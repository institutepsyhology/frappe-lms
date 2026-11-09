"""Permit shared mobile numbers on the selected Frappe site only.

Run in the bench sites directory after a verified database backup. The caller
must pass the exact expected site name and use a separate stage for testing.
"""
import json
import sys
import frappe
from frappe.custom.doctype.property_setter.property_setter import make_property_setter


def main(site):
    if site not in ('access-stage2.local', 'my-lk.mv-centr.ru'):
        raise RuntimeError('unexpected_site')
    frappe.init(site=site)
    frappe.connect()
    try:
        if int(frappe.db.get_single_value('System Settings', 'allow_login_using_mobile_number') or 0):
            raise RuntimeError('mobile_login_must_be_disabled')
        setters = frappe.get_all('Property Setter', filters={'doc_type':'User','field_name':'mobile_no','property':'unique'}, fields=['name','value'])
        if len(setters)>1 or (setters and str(setters[0]['value'])!='0'):
            raise RuntimeError('unexpected_property_setter')
        indexes = frappe.db.sql('SHOW INDEX FROM `tabUser` WHERE Column_name = %s', ('mobile_no',), as_dict=True)
        if len(indexes)!=1 or indexes[0]['Key_name']!='mobile_no' or indexes[0]['Seq_in_index']!=1:
            raise RuntimeError('unexpected_mobile_index')
        was_unique = indexes[0]['Non_unique']==0
        if not setters:
            make_property_setter('User','mobile_no','unique','0','Check')
            frappe.db.commit()
        frappe.clear_cache(doctype='User')
        if int(frappe.get_meta('User').get_field('mobile_no').unique or 0)!=0:
            raise RuntimeError('property_setter_not_applied')
        if was_unique:
            frappe.db.sql('ALTER TABLE `tabUser` DROP INDEX `mobile_no`, ADD INDEX `mobile_no` (`mobile_no`)')
        indexes = frappe.db.sql('SHOW INDEX FROM `tabUser` WHERE Column_name = %s', ('mobile_no',), as_dict=True)
        if len(indexes)!=1 or indexes[0]['Non_unique']!=1:
            raise RuntimeError('index_not_updated')
        print(json.dumps({'site':site,'mobile_unique':False,'mobile_login':False,'indexed':True}))
    finally:
        frappe.destroy()


if __name__ == '__main__':
    if len(sys.argv)!=2:
        raise SystemExit('expected site')
    main(sys.argv[1])

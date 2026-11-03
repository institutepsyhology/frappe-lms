"""Install source identifiers needed to reconcile migrated AVO content.

Run from a trusted Frappe bench against the intended site only. This script
contains no source content, credentials, contact data, or video URLs.
"""
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


def execute():
    fields = {}
    for doctype, label in (("LMS Course", "AVO Course ID"), ("Course Lesson", "AVO Lesson ID")):
        fields[doctype] = [
            {"fieldname": "custom_avo_id", "label": label, "fieldtype": "Data",
             "insert_after": "title", "search_index": 1, "no_copy": 1},
            {"fieldname": "custom_avo_account", "label": "AVO Account", "fieldtype": "Data",
             "insert_after": "custom_avo_id", "search_index": 1, "no_copy": 1},
        ]
    create_custom_fields(fields, update=True)

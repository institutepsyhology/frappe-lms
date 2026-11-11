"""Install source identity fields for imported AVO users on a selected site."""

from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


def execute():
    create_custom_fields({"User": [
        {"fieldname": "custom_avo_contact_id", "label": "AVO Contact ID", "fieldtype": "Data",
         "insert_after": "email", "search_index": 1, "no_copy": 1, "permlevel": 1},
        {"fieldname": "custom_avo_account", "label": "AVO Account", "fieldtype": "Data",
         "insert_after": "custom_avo_contact_id", "no_copy": 1, "permlevel": 1},
        {"fieldname": "custom_avo_telegram_id", "label": "Telegram ID", "fieldtype": "Data",
         "insert_after": "custom_avo_account", "no_copy": 1, "permlevel": 1},
        {"fieldname": "custom_avo_telegram_username", "label": "Telegram Username", "fieldtype": "Data",
         "insert_after": "custom_avo_telegram_id", "no_copy": 1, "permlevel": 1},
        {"fieldname": "custom_avo_vk_id", "label": "VK ID", "fieldtype": "Data",
         "insert_after": "custom_avo_telegram_username", "no_copy": 1, "permlevel": 1},
        {"fieldname": "custom_avo_vk_username", "label": "VK Username", "fieldtype": "Data",
         "insert_after": "custom_avo_vk_id", "no_copy": 1, "permlevel": 1},
        {"fieldname": "custom_no_marketing_email", "label": "Не отправлять рассылки", "fieldtype": "Check",
         "insert_after": "custom_avo_vk_username", "default": "0", "no_copy": 1, "permlevel": 1},
    ]}, update=True)

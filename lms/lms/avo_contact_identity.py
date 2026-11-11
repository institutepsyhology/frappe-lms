"""Source identity fields for contacts that do not have a usable email."""
import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


def execute():
    if frappe.local.site not in ('access-stage2.local', 'my-lk.mv-centr.ru', 'my-lk.iomp.ru', 'my-lk.mastervision.su'):
        raise RuntimeError('unexpected_site')
    fields = [
        {'fieldname':'custom_avo_contact_id','label':'AVO Contact ID','fieldtype':'Data',
         'insert_after':'first_name','unique':1,'no_copy':1,'permlevel':1},
        {'fieldname':'custom_avo_account','label':'AVO Account','fieldtype':'Data',
         'insert_after':'custom_avo_contact_id','no_copy':1,'permlevel':1},
        {'fieldname':'custom_avo_telegram_id','label':'AVO Telegram ID','fieldtype':'Data',
         'insert_after':'custom_avo_account','no_copy':1,'permlevel':1},
        {'fieldname':'custom_avo_telegram_username','label':'AVO Telegram Username','fieldtype':'Data',
         'insert_after':'custom_avo_telegram_id','no_copy':1,'permlevel':1},
        {'fieldname':'custom_avo_vk_id','label':'AVO VK ID','fieldtype':'Data',
         'insert_after':'custom_avo_telegram_username','no_copy':1,'permlevel':1},
        {'fieldname':'custom_avo_vk_username','label':'AVO VK Username','fieldtype':'Data',
         'insert_after':'custom_avo_vk_id','no_copy':1,'permlevel':1},
        {'fieldname':'custom_avo_source_email','label':'AVO Source Email','fieldtype':'Data',
         'insert_after':'custom_avo_vk_username','no_copy':1,'permlevel':1},
    ]
    create_custom_fields({'Contact':fields}, update=True)

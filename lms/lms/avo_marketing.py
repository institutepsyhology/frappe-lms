"""Marketing-only preferences; transactional mail is deliberately unaffected."""
import frappe


SITE_ACCOUNTS = {'my-lk.mv-centr.ru': 'mv-centr', 'my-lk.iomp.ru': 'iomp',
                 'my-lk.mastervision.su': 'mastervision', 'access-stage2.local': 'mv-centr'}


def is_blocked(email):
    """Fail closed for a shared address if any matching record opted out."""
    if not isinstance(email, str) or not email.strip():
        return True
    email = email.strip().lower()
    if frappe.db.sql("""select 1 from `tabUser` where lower(email)=%s
                       and custom_no_marketing_email=1 limit 1""", (email,)):
        return True
    return bool(frappe.db.sql("""select 1 from `tabContact` c
        left join `tabContact Email` e on e.parent=c.name and e.parenttype='Contact'
        where c.custom_no_marketing_email=1 and
        (lower(e.email_id)=%s or lower(c.custom_avo_source_email)=%s) limit 1""", (email, email)))


def protect_group_member(doc, method=None):
    if doc.email and is_blocked(doc.email):
        doc.unsubscribed = 1


def protect_document(doc, method=None):
    if not doc.get('custom_no_marketing_email'):
        return
    email = doc.get('email') if doc.doctype == 'User' else doc.get('email_id')
    if email:
        frappe.db.sql('update `tabEmail Group Member` set unsubscribed=1 where email=%s', (email,))


def protect_existing_groups(account, ids):
    placeholders = ','.join(['%s'] * len(ids))
    frappe.db.sql(f"""update `tabEmail Group Member` m join `tabUser` u on m.email=u.email
        set m.unsubscribed=1 where u.custom_avo_account=%s
        and u.custom_avo_contact_id in ({placeholders}) and u.custom_no_marketing_email=1""", [account] + ids)
    frappe.db.sql(f"""update `tabEmail Group Member` m join `tabContact Email` e on m.email=e.email_id
        join `tabContact` c on c.name=e.parent and e.parenttype='Contact'
        set m.unsubscribed=1 where c.custom_avo_account=%s
        and c.custom_avo_contact_id in ({placeholders}) and c.custom_no_marketing_email=1""", [account] + ids)


@frappe.whitelist(methods=['POST'])
def apply_source_optouts(account, ids):
    """Set only positive historical opt-outs; never clear a newer preference."""
    if frappe.session.user != 'Administrator' or SITE_ACCOUNTS.get(frappe.local.site) != account:
        frappe.throw('Administrator and matching source account required', frappe.PermissionError)
    ids = frappe.parse_json(ids)
    if not isinstance(ids, list) or not ids or len(ids) > 250 or any(
        not isinstance(i, str) or not i.isdigit() or len(i) > 20 for i in ids
    ):
        frappe.throw('Invalid source IDs', frappe.ValidationError)
    ids = list(set(ids))
    placeholders = ','.join(['%s'] * len(ids))
    for doctype in ('User', 'Contact'):
        frappe.db.sql(f"""update `tab{doctype}` set custom_no_marketing_email=1
            where custom_avo_account=%s and custom_avo_contact_id in ({placeholders})
            and coalesce(custom_no_marketing_email,0)=0""", [account] + ids)
    protect_existing_groups(account, ids)
    return {'processed': len(ids)}

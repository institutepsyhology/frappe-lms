"""Trusted bench operator: atomically import a small selected no-email batch.

Run with the bench Python from its sites directory. Read a private JSON envelope
from stdin: {"account": "mv-centr", "records": [Contact payload, ...]}.
The normal Contact lifecycle still validates each record; only its internal name
is explicitly assigned. No existing document is updated, renamed, or merged.
"""
import copy
import html
import json
import re
import sys


SITE = "my-lk.mv-centr.ru"
ACCOUNT = "mv-centr"
MAX_RECORDS = 10
TEXT_FIELDS = (
    "first_name", "middle_name", "last_name", "custom_avo_contact_id",
    "custom_avo_account", "custom_avo_telegram_id", "custom_avo_telegram_username",
    "custom_avo_vk_id", "custom_avo_vk_username", "custom_avo_source_email",
)
REQUIRED_FIELDS = frozenset((*TEXT_FIELDS, "doctype", "custom_no_marketing_email"))
EMAIL = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+\Z")


class ImportRejected(ValueError):
    """A safe machine-readable code; never include source values in its text."""


def _records(envelope):
    if (type(envelope) is not dict or set(envelope) != {"account", "records"}
            or envelope["account"] != ACCOUNT or type(envelope["records"]) is not list
            or not 1 <= len(envelope["records"]) <= MAX_RECORDS):
        raise ImportRejected("invalid_envelope")
    records = copy.deepcopy(envelope["records"])
    seen = set()
    for data in records:
        if (type(data) is not dict or not REQUIRED_FIELDS <= set(data)
                or set(data) - REQUIRED_FIELDS - {"phone_nos"}
                or data["doctype"] != "Contact" or data["custom_avo_account"] != ACCOUNT
                or any(type(data[key]) is not str for key in TEXT_FIELDS)
                or type(data["custom_no_marketing_email"]) is not int
                or data["custom_no_marketing_email"] not in (0, 1)
                or not (data["first_name"] or data["last_name"])):
            raise ImportRejected("invalid_record")
        ident = data["custom_avo_contact_id"]
        if not re.fullmatch(r"[1-9][0-9]{0,17}", ident):
            raise ImportRejected("invalid_source_id")
        if ident in seen:
            raise ImportRejected("duplicate_source_id")
        seen.add(ident)
        if EMAIL.fullmatch(data["custom_avo_source_email"].strip()):
            raise ImportRejected("usable_email_not_allowed")
        phones = data.get("phone_nos", [])
        if (type(phones) is not list or len(phones) > 1
                or any(type(row) is not dict or set(row) != {"phone", "is_primary_mobile_no"}
                       or type(row["phone"]) is not str or not row["phone"]
                       or type(row["is_primary_mobile_no"]) is not int
                       or row["is_primary_mobile_no"] != 1 for row in phones)):
            raise ImportRejected("invalid_phone")
    return records


def _matches(doc, data):
    for key in TEXT_FIELDS:
        actual, expected = doc.get(key) or "", data[key]
        # Frappe's name-field sanitization may decode HTML entities. Source IDs,
        # social profiles and all other values must still match exactly.
        if key in ("first_name", "middle_name", "last_name"):
            actual, expected = html.unescape(actual), html.unescape(expected)
        if actual != expected:
            return False
    if doc.get("custom_no_marketing_email") != data["custom_no_marketing_email"]:
        return False
    if doc.get("email_id") or doc.get("email_ids") or doc.get("user"):
        return False
    phones = [{"phone": row.get("phone"), "is_primary_mobile_no": row.get("is_primary_mobile_no")}
              for row in (doc.get("phone_nos") or [])]
    expected = data.get("phone_nos", [])
    if phones != expected:
        return False
    return (doc.get("mobile_no") or "") == (expected[0]["phone"] if expected else "")


def import_records(frappe, envelope):
    """Insert only selected new cards; rollback the whole batch on any error."""
    if frappe.local.site != SITE:
        raise ImportRejected("wrong_site")
    if frappe.session.user != "Administrator":
        raise ImportRejected("wrong_operator")
    records = _records(envelope)
    frappe.db.begin()
    try:
        plan = []
        for data in records:
            ident = data["custom_avo_contact_id"]
            filters = {"custom_avo_contact_id": ident}
            users = frappe.get_all("User", filters=filters, fields=["name"], limit_page_length=2)
            contacts = frappe.get_all("Contact", filters=filters,
                                      fields=["name", "custom_avo_account"], limit_page_length=2)
            if users or len(contacts) > 1:
                raise ImportRejected("source_id_conflict")
            if contacts:
                current = frappe.get_doc("Contact", contacts[0]["name"])
                if contacts[0]["custom_avo_account"] != ACCOUNT or not _matches(current, data):
                    raise ImportRejected("existing_contact_mismatch")
                plan.append((data, contacts[0]["name"], False))
                continue
            name = "avo-mv-centr-contact-" + ident
            if frappe.db.exists("Contact", name):
                raise ImportRejected("internal_name_conflict")
            plan.append((data, name, True))

        results = []
        for data, name, create in plan:
            if create:
                frappe.get_doc(data).insert(set_name=name)
            saved = frappe.get_doc("Contact", name)
            if not _matches(saved, data):
                raise ImportRejected("readback_mismatch")
            results.append({"contact_id": int(data["custom_avo_contact_id"]),
                            "status": "created_verified" if create else "already_present"})
        frappe.db.commit()
        return results
    except Exception:
        frappe.db.rollback()
        raise


def main():
    import frappe

    try:
        raw = sys.stdin.read(250001)
        if len(raw) > 250000:
            raise ImportRejected("payload_too_large")
        try:
            envelope = json.loads(raw)
        except (ValueError, TypeError):
            raise ImportRejected("invalid_json") from None
        frappe.init(site=SITE)
        frappe.connect()
        frappe.set_user("Administrator")
        result = import_records(frappe, envelope)
        print(json.dumps({"ok": True, "results": result}))
        return 0
    except ImportRejected as exc:
        print(json.dumps({"ok": False, "error": str(exc)}))
        return 1
    except Exception:
        print(json.dumps({"ok": False, "error": "import_failed"}))
        return 1
    finally:
        frappe.destroy()


if __name__ == "__main__":
    raise SystemExit(main())

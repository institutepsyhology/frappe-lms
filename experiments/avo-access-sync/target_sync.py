"""Trusted MVC bench operator for immutable AVO access snapshots.

Store snapshots independently from activation. Only the normal LMS enrollment,
policy and grant models participate in runtime access; this registry is a source
ledger. JSON-lines input/output never returns names, addresses or source payloads.
"""
import copy
import hashlib
import json
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from zoneinfo import ZoneInfo


SITE = "my-lk.mv-centr.ru"
ACCOUNT = "mv-centr"
ORIGIN = "https://shop.mv-centr.ru"
DOCTYPE = "AVO Course Access"
MAX_BATCH = 100
STATUSES = "Stored\nPending Contact\nPending Course\nNeeds Review\nApplied\nFrozen\nExpired"
DATE_FIELDS = ("opens_at", "closes_at", "report_check_ends_at", "training_start_at", "effective_closes_at")
RECORD_FIELDS = {"schema_version", "account", "origin", "source_access_id", "source_contact_id",
                 "source_course_id", "source_snapshot_hash", "captured_at", "access", "lessons"}
ACCESS_FIELDS = set(DATE_FIELDS) | {"frozen", "ignore_course_end", "day_access_shift", "personal_term",
                                  "derived_status", "as_of"}
LESSON_FIELDS = {"id", "assigned", "accessible", "hidden", "day_access", "number", "can_edit_accessible"}
FIELDS = [
    {"fieldname": "account", "fieldtype": "Data", "reqd": 1, "search_index": 1},
    {"fieldname": "source_access_id", "fieldtype": "Data", "reqd": 1, "unique": 1, "search_index": 1},
    {"fieldname": "source_contact_id", "fieldtype": "Data", "reqd": 1, "search_index": 1},
    {"fieldname": "source_course_id", "fieldtype": "Data", "reqd": 1, "search_index": 1},
    {"fieldname": "source_snapshot_hash", "fieldtype": "Data", "reqd": 1},
    {"fieldname": "payload_hash", "fieldtype": "Data", "reqd": 1},
    {"fieldname": "source_payload", "fieldtype": "Long Text", "reqd": 1},
    {"fieldname": "captured_at", "fieldtype": "Datetime", "reqd": 1},
    {"fieldname": "mapped_user", "fieldtype": "Link", "options": "User"},
    {"fieldname": "mapped_contact", "fieldtype": "Link", "options": "Contact"},
    {"fieldname": "mapped_course", "fieldtype": "Link", "options": "LMS Course"},
    {"fieldname": "grant", "fieldtype": "Link", "options": "LMS Access Grant"},
    {"fieldname": "enrollment", "fieldtype": "Link", "options": "LMS Enrollment"},
    {"fieldname": "sync_status", "fieldtype": "Select", "options": STATUSES, "reqd": 1, "search_index": 1},
    {"fieldname": "review_reason", "fieldtype": "Data"},
]
LABELS = {
    "account": "Аккаунт АВО", "source_access_id": "ID связи АВО",
    "source_contact_id": "ID контакта АВО", "source_course_id": "ID курса АВО",
    "source_snapshot_hash": "Контрольная сумма исходного снимка",
    "payload_hash": "Контрольная сумма настроек", "source_payload": "Настройки из архива АВО",
    "captured_at": "Дата снимка", "mapped_user": "Пользователь Frappe",
    "mapped_contact": "Контакт Frappe", "mapped_course": "Курс Frappe",
    "grant": "Личный доступ LMS", "enrollment": "Зачисление LMS",
    "sync_status": "Состояние переноса", "review_reason": "Причина ожидания",
}
for _field in FIELDS:
    _field.update(label=LABELS[_field["fieldname"]], read_only=1)
    if _field["fieldname"] in ("source_contact_id", "source_course_id", "sync_status"):
        _field["in_list_view"] = 1
DERIVED_FIELDS = ("mapped_user", "mapped_contact", "mapped_course", "sync_status", "review_reason")
REFRESHABLE_STATUSES = {"Stored", "Pending Contact", "Pending Course", "Needs Review"}


class Rejected(ValueError):
    """Safe fixed code only; never interpolate source data into errors."""


def _require(fr):
    if fr.local.site != SITE:
        raise Rejected("wrong_site")
    if fr.session.user != "Administrator":
        raise Rejected("wrong_operator")


def _id(value):
    return type(value) is str and re.fullmatch(r"[1-9][0-9]{0,17}", value) is not None


def _instant(value):
    if type(value) is not str:
        raise Rejected("invalid_timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise Rejected("invalid_timestamp") from None
    if parsed.tzinfo is None:
        raise Rejected("timestamp_without_timezone")
    return parsed


def _site_time(value):
    return _instant(value).astimezone(ZoneInfo("Europe/Moscow")).replace(tzinfo=None).isoformat(sep=" ")


def _canonical(record):
    return json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _validate_records(records):
    if type(records) is not list or not 1 <= len(records) <= MAX_BATCH:
        raise Rejected("invalid_batch")
    seen = set()
    result = copy.deepcopy(records)
    for record in result:
        if (type(record) is not dict or set(record) != RECORD_FIELDS
                or type(record["schema_version"]) is not int or record["schema_version"] != 1
                or record["account"] != ACCOUNT or record["origin"] != ORIGIN
                or any(not _id(record[key]) for key in ("source_access_id", "source_contact_id", "source_course_id"))
                or type(record["source_snapshot_hash"]) is not str
                or not re.fullmatch(r"[0-9a-f]{64}", record["source_snapshot_hash"])):
            raise Rejected("invalid_source_record")
        if int(record["source_access_id"]) > 100997 or record["source_access_id"] in seen:
            raise Rejected("source_access_outside_scope_or_duplicate")
        seen.add(record["source_access_id"])
        _instant(record["captured_at"])
        access = record["access"]
        if (type(access) is not dict or set(access) != ACCESS_FIELDS
                or any(access[key] is not None and type(access[key]) is not bool for key in ("frozen", "ignore_course_end"))
                or access["day_access_shift"] is not None and type(access["day_access_shift"]) is not int
                or access["personal_term"] not in ("unlimited", "until_date", "unset", "unknown")
                or access["derived_status"] not in ("unknown", "frozen", "expired", "scheduled")):
            raise Rejected("invalid_access_shape")
        if access["as_of"] is not None:
            _instant(access["as_of"])
        for key in DATE_FIELDS:
            date = access[key]
            if (type(date) is not dict or set(date) != {"raw", "iso", "kind"}
                    or date["kind"] not in ("datetime", "unlimited", "unset", "unknown", "invalid")
                    or date["raw"] is not None and type(date["raw"]) is not str
                    or date["iso"] is not None and type(date["iso"]) is not str):
                raise Rejected("invalid_source_date")
            if date["kind"] == "datetime":
                _instant(date["iso"])
            elif date["iso"] is not None:
                raise Rejected("invalid_source_date")
        if type(record["lessons"]) is not list or len(record["lessons"]) > 5000:
            raise Rejected("invalid_lessons")
        lesson_ids = set()
        for lesson in record["lessons"]:
            if (type(lesson) is not dict or set(lesson) != LESSON_FIELDS or not _id(lesson["id"])
                    or lesson["id"] in lesson_ids
                    or any(lesson[key] is not None and type(lesson[key]) is not bool
                           for key in ("assigned", "accessible", "hidden", "can_edit_accessible"))
                    or any(lesson[key] is not None and type(lesson[key]) is not int for key in ("day_access", "number"))):
                raise Rejected("invalid_lesson_shape")
            lesson_ids.add(lesson["id"])
        _canonical(record)
    return result


def ensure_schema(fr):
    """Explicit DDL phase; call before store_batch, never inside its transaction."""
    _require(fr)
    if not fr.db.exists("DocType", DOCTYPE):
        fr.get_doc({"doctype": "DocType", "name": DOCTYPE, "module": "LMS", "custom": 1,
                    "autoname": "hash", "title_field": "source_access_id", "track_changes": 0,
                    "engine": "InnoDB", "fields": FIELDS,
                    "permissions": [{"role": "System Manager", "read": 1}]}).insert()
        fr.db.commit()
    meta = fr.get_meta(DOCTYPE)
    if not meta.custom or meta.title_field != "source_access_id":
        raise Rejected("unexpected_registry_doctype")
    for expected in FIELDS:
        actual = meta.get_field(expected["fieldname"])
        if (not actual or actual.fieldtype != expected["fieldtype"] or not actual.read_only
                or (expected.get("options") and actual.options != expected["options"])
                or any(expected.get(key) and not actual.get(key) for key in ("reqd", "unique", "search_index", "in_list_view"))):
            raise Rejected("registry_schema_mismatch")
    if (len(meta.permissions) != 1 or meta.permissions[0].role != "System Manager"
            or not meta.permissions[0].read
            or any(meta.permissions[0].get(key) for key in ("create", "write", "delete", "share", "export"))):
        raise Rejected("registry_permissions_mismatch")
    return {"doctype": DOCTYPE, "ready": True}


def _mapping(fr, records):
    contact_ids = sorted({record["source_contact_id"] for record in records})
    course_ids = sorted({record["source_course_id"] for record in records})
    def load(doctype, id_field, ids, extra=()):
        rows = fr.get_all(doctype, filters={"custom_avo_account": ACCOUNT, id_field: ("in", ids)},
                          fields=["name", id_field, *extra], limit_page_length=0)
        indexed = defaultdict(list)
        for row in rows:
            indexed[str(row[id_field])].append(row)
        return indexed
    return (load("User", "custom_avo_contact_id", contact_ids, ("enabled",)),
            load("Contact", "custom_avo_contact_id", contact_ids, ("user",)),
            load("LMS Course", "custom_avo_id", course_ids))


def _mapped(record, mappings):
    users, contacts, courses = mappings
    uid, cid = record["source_contact_id"], record["source_course_id"]
    u, c, course = users[uid], contacts[uid], courses[cid]
    result = {"mapped_user": None, "mapped_contact": None, "mapped_course": None,
              "sync_status": "Stored", "review_reason": None}
    if len(u) > 1 or len(c) > 1 or len(course) > 1 or (u and c and c[0].get("user") != u[0]["name"]):
        result.update(sync_status="Needs Review", review_reason="ambiguous_target_mapping")
        return result
    if u: result["mapped_user"] = u[0]["name"]
    if c: result["mapped_contact"] = c[0]["name"]
    if course: result["mapped_course"] = course[0]["name"]
    if not u:
        result.update(sync_status="Pending Contact", review_reason="contact_without_login" if c else "contact_not_migrated")
    elif not course:
        result.update(sync_status="Pending Course", review_reason="course_not_migrated")
    elif not u[0].get("enabled"):
        result.update(sync_status="Needs Review", review_reason="user_disabled")
    return result


def _ledger_row(record, mappings):
    payload = _canonical(record)
    return {"name": "avo-mv-centr-access-" + record["source_access_id"], "account": ACCOUNT,
            **{key: record[key] for key in ("source_access_id", "source_contact_id", "source_course_id", "source_snapshot_hash")},
            "payload_hash": hashlib.sha256(payload.encode("utf-8")).hexdigest(), "source_payload": payload,
            "captured_at": _site_time(record["captured_at"]), **_mapped(record, mappings)}


def _existing(fr, records):
    return {row["name"]: row for row in fr.get_all(DOCTYPE,
        filters={"name": ("in", ["avo-mv-centr-access-" + r["source_access_id"] for r in records])},
        fields=["name", "account", "source_access_id", "source_contact_id", "source_course_id", "source_snapshot_hash",
                "payload_hash", "source_payload", *DERIVED_FIELDS, "grant", "enrollment"], limit_page_length=0)}


def _same_source(actual, expected):
    return all(actual.get(key) == expected[key] for key in ("account", "source_access_id", "source_contact_id",
        "source_course_id", "source_snapshot_hash", "payload_hash", "source_payload"))


def store_batch(fr, records):
    """Atomic bulk insert of immutable snapshots; repeats never rewrite a ledger."""
    _require(fr)
    records = _validate_records(records)
    if not fr.db.exists("DocType", DOCTYPE):
        raise Rejected("registry_schema_not_initialized")
    fr.db.begin()
    try:
        mappings, existing = _mapping(fr, records), _existing(fr, records)
        expected = [_ledger_row(record, mappings) for record in records]
        new, refreshed = [], 0
        derived_expected = {}
        for row in expected:
            if row["name"] in existing:
                old = existing[row["name"]]
                if not _same_source(old, row):
                    raise Rejected("source_snapshot_changed")
                if not old.get("grant") and not old.get("enrollment") and old["sync_status"] in REFRESHABLE_STATUSES:
                    derived_expected[row["name"]] = {key: row[key] for key in DERIVED_FIELDS}
                else:
                    derived_expected[row["name"]] = {key: old.get(key) for key in DERIVED_FIELDS}
            else:
                new.append(row)
                derived_expected[row["name"]] = {key: row[key] for key in DERIVED_FIELDS}
        for name, old in existing.items():
            changes = {key: value for key, value in derived_expected[name].items()
                       if (old.get(key) or None) != (value or None)}
            if changes:
                fr.db.set_value(DOCTYPE, name, changes)
                refreshed += 1
        if new:
            stamp = datetime.now(timezone.utc).astimezone(ZoneInfo("Europe/Moscow")).replace(tzinfo=None).isoformat(sep=" ")
            columns = ["name", "creation", "modified", "owner", "modified_by", "docstatus", "idx"] + [f["fieldname"] for f in FIELDS]
            values = []
            for row in new:
                full = {**row, "creation": stamp, "modified": stamp, "owner": "Administrator",
                        "modified_by": "Administrator", "docstatus": 0, "idx": 0}
                values.append([full.get(column) for column in columns])
            fr.db.bulk_insert(DOCTYPE, fields=columns, values=values)
        saved = _existing(fr, records)
        if any(row["name"] not in saved or not _same_source(saved[row["name"]], row) for row in expected):
            raise Rejected("ledger_readback_mismatch")
        if any(any((saved[name].get(key) or None) != (value or None) for key, value in values.items())
               for name, values in derived_expected.items()):
            raise Rejected("ledger_mapping_readback_mismatch")
        fr.db.commit()
        return {"stored": len(new), "already_stored": len(records) - len(new), "refreshed": refreshed,
                "statuses": dict(Counter(saved[row["name"]]["sync_status"] for row in expected))}
    except Exception:
        fr.db.rollback()
        raise


def audit(fr):
    _require(fr)
    if not fr.db.exists("DocType", DOCTYPE):
        return {"registry_exists": False, "ledger_count": 0}
    rows = fr.get_all(DOCTYPE, fields=["sync_status"], limit_page_length=0)
    return {"registry_exists": True, "ledger_count": len(rows),
            "statuses": dict(Counter(row["sync_status"] for row in rows))}


def main():
    import frappe
    frappe.init(site=SITE)
    frappe.connect()
    frappe.set_user("Administrator")
    try:
        for line in sys.stdin:
            try:
                if len(line) > 5_000_000:
                    raise Rejected("request_too_large")
                request = json.loads(line)
                if type(request) is not dict:
                    raise Rejected("invalid_request")
                operation = request.get("op")
                if operation == "audit": result = audit(frappe)
                elif operation == "schema": result = ensure_schema(frappe)
                elif operation == "store": result = store_batch(frappe, request.get("records"))
                elif operation == "finalize":
                    print(json.dumps({"ok": True, "result": audit(frappe)}), flush=True)
                    break
                else: raise Rejected("unknown_operation")
                print(json.dumps({"ok": True, "result": result}), flush=True)
            except Rejected as exc:
                print(json.dumps({"ok": False, "error": str(exc)}), flush=True)
                return 1
            except Exception:
                frappe.db.rollback()
                print(json.dumps({"ok": False, "error": "target_sync_failed"}), flush=True)
                return 1
        return 0
    finally:
        frappe.destroy()


if __name__ == "__main__":
    raise SystemExit(main())

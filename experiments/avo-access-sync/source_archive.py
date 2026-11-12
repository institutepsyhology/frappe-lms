"""Stream identity-only MVC access records from the verified historical archive.

This reader never decides current access or merges different access-link IDs.
File databases open in SQLite read-only mode. An existing connection is accepted
for in-memory tests; the reader runs SELECT statements only and does not own it.
"""
import hashlib
import json
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path


ORIGIN = "https://shop.mv-centr.ru"
ACCOUNT = "mv-centr"
VERIFIED_FIRST_ID = 1
VERIFIED_LAST_ID = 100997
FOREIGN_EXAMPLE_ID = "446462"
MAX_LESSONS = 5000
DATE_FIELDS = ("opens_at", "closes_at", "report_check_ends_at", "training_start_at",
               "effective_closes_at")
ACCESS_FIELDS = frozenset((*DATE_FIELDS, "frozen", "ignore_course_end", "day_access_shift",
                           "personal_term", "derived_status", "as_of"))
LESSON_FIELDS = ("assigned", "accessible", "hidden", "day_access", "number", "can_edit_accessible")
KNOWN_LESSON_FIELDS = frozenset(("id", *LESSON_FIELDS, "title", "category_id", "category",
                                 "raw", "source_all", "source_assigned"))


class SafeCode(ValueError):
    """Only fixed diagnostic codes are raised; source values never enter errors."""


def source_id(value):
    if type(value) is int:
        value = str(value)
    if (type(value) is not str or not re.fullmatch(r"[1-9][0-9]{0,15}", value)
            or int(value) > 2**53 - 1):
        raise SafeCode("invalid_source_id")
    return value


def _iso(value):
    if type(value) is not str:
        raise SafeCode("invalid_timestamp")
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise SafeCode("invalid_timestamp") from None
    if result.utcoffset() is None:
        raise SafeCode("timestamp_without_timezone")
    return result


def _date(value):
    if (type(value) is not dict or set(value) != {"raw", "iso", "kind"}
            or value["kind"] not in ("datetime", "unlimited", "unset", "unknown", "invalid")
            or (value["raw"] is not None and type(value["raw"]) is not str)):
        raise SafeCode("invalid_date_structure")
    if value["kind"] == "datetime":
        _iso(value["iso"])
    elif value["iso"] is not None:
        raise SafeCode("invalid_date_structure")
    return dict(value)


def _json(value):
    if type(value) is not str:
        raise SafeCode("invalid_archive_json")
    try:
        return json.loads(value)
    except (ValueError, TypeError):
        raise SafeCode("invalid_archive_json") from None


def _access(value):
    if type(value) is not dict or set(value) != ACCESS_FIELDS:
        raise SafeCode("unknown_access_structure")
    result = dict(value)
    for key in DATE_FIELDS:
        result[key] = _date(value[key])
    for key in ("frozen", "ignore_course_end"):
        if value[key] is not None and type(value[key]) is not bool:
            raise SafeCode("invalid_access_flag")
    if value["day_access_shift"] is not None and type(value["day_access_shift"]) is not int:
        raise SafeCode("invalid_access_shift")
    if value["personal_term"] not in ("unlimited", "until_date", "unset", "unknown"):
        raise SafeCode("invalid_personal_term")
    if value["derived_status"] not in ("unknown", "frozen", "expired", "scheduled"):
        raise SafeCode("invalid_historical_status")
    if value["as_of"] is not None:
        _iso(value["as_of"])
    return result


def _lessons(db, snapshot_id):
    result, seen = [], set()
    rows = db.execute("SELECT lesson_id,lesson_json FROM lessons WHERE snapshot_id=? ORDER BY ordinal",
                      (snapshot_id,))
    for ident, raw in rows:
        if len(result) >= MAX_LESSONS:
            raise SafeCode("too_many_lessons")
        value = _json(raw)
        if type(value) is not dict or set(value) - KNOWN_LESSON_FIELDS:
            raise SafeCode("unknown_lesson_structure")
        ident = source_id(ident)
        if source_id(value.get("id")) != ident or ident in seen:
            raise SafeCode("ambiguous_lesson_id")
        seen.add(ident)
        item = {"id": ident}
        for key in LESSON_FIELDS:
            field = value.get(key)
            expected = int if key in ("day_access", "number") else bool
            if field is not None and type(field) is not expected:
                raise SafeCode("invalid_lesson_field_type")
            item[key] = field
        result.append(item)
    return result


def iter_records(database, excluded_contact_ids=(), excluded_course_ids=()):
    """Yield verified-range source links in stable lexical source-ID order.

    Only scalar metadata/access JSON is read in the main indexed cursor. Raw
    snapshot JSON is fetched for one record only when its hash/capture is absent.
    Missing flags remain null; additional permission structures stop the reader.
    """
    excluded_contacts = {source_id(value) for value in excluded_contact_ids}
    excluded_courses = {source_id(value) for value in excluded_course_ids}
    own = not isinstance(database, sqlite3.Connection)
    try:
        db = (sqlite3.connect(Path(database).resolve().as_uri() + "?mode=ro", uri=True)
              if own else database)
    except (OSError, sqlite3.Error):
        raise SafeCode("archive_open_failed") from None
    try:
        rows = db.execute("""SELECT p.link_key,p.snapshot_id,a.contact_id,a.course_id,
                  s.content_sha256,o.captured_at,a.access_json
            FROM latest p JOIN course_access a ON a.snapshot_id=p.snapshot_id
            JOIN snapshots s ON s.id=p.snapshot_id
            LEFT JOIN observations o ON o.id=p.observation_id
            WHERE p.namespace=? AND p.successful=1 AND s.successful=1
              AND p.link_key<>? AND CAST(p.link_key AS INTEGER) BETWEEN ? AND ?
            ORDER BY p.link_key""", (ORIGIN, FOREIGN_EXAMPLE_ID, VERIFIED_FIRST_ID, VERIFIED_LAST_ID))
        for link, snapshot, contact, course, digest, captured, raw_access in rows:
            link, contact, course = source_id(link), source_id(contact), source_id(course)
            if contact in excluded_contacts or course in excluded_courses:
                continue
            access = _access(_json(raw_access))
            raw_snapshot = None
            snapshot_value = None
            if not digest or not captured:
                raw_snapshot = db.execute("SELECT record_json FROM snapshots WHERE id=?", (snapshot,)).fetchone()[0]
                snapshot_value = _json(raw_snapshot)
                if type(snapshot_value) is not dict:
                    raise SafeCode("invalid_snapshot_structure")
            if not digest:
                digest = hashlib.sha256(raw_snapshot.encode("utf-8")).hexdigest()
            if type(digest) is not str or not re.fullmatch(r"[0-9a-f]{64}", digest):
                raise SafeCode("invalid_snapshot_hash")
            if not captured:
                source = snapshot_value.get("source") or {}
                if type(source) is not dict:
                    raise SafeCode("invalid_snapshot_source")
                captured = source.get("captured_at") or access["as_of"]
            if not captured:
                raise SafeCode("missing_capture_time")
            yield {"schema_version": 1, "account": ACCOUNT, "origin": ORIGIN,
                   "source_access_id": link, "source_contact_id": contact, "source_course_id": course,
                   "source_snapshot_hash": digest,
                   "captured_at": _iso(captured).astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
                   "access": access, "lessons": _lessons(db, snapshot)}
    except sqlite3.Error:
        raise SafeCode("archive_query_failed") from None
    finally:
        if own:
            db.close()

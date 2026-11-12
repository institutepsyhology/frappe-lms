"""Restore explicitly recorded AVO availability through native LMS grants.

This is a conservative migration boundary, not an inferred original schedule.
An accessible source checkbox is restored no earlier than its source snapshot;
future offset formulas, prerequisites, progress and retention are not invented.
"""
import hashlib
import json
from datetime import datetime, timedelta, timezone

import target_sync as target


DATE_KEYS = {"starts_at", "ends_at", "opens_at", "course_ends_at", "frozen_at"}
POLICY_VALUES = {"enabled": 1, "default_personal_end_type": "Unknown", "default_personal_end_at": None,
    "default_personal_end_days": 0, "global_end_type": "Unlimited", "global_end_at": None,
    "completed_retention_type": "None", "completed_retention_days": 0,
    "visited_retention_type": "None", "visited_retention_days": 0, "lessons": []}


def _check(fr, allow):
    target._require(fr)
    if allow is not True:
        raise target.Rejected("general_unlimited_not_authorized")
    if fr.conf.get("individual_access_release_enabled") is not True:
        raise target.Rejected("individual_access_release_disabled")


def _source(ledger):
    try:
        record = json.loads(ledger.get("source_payload") or "")
        target._validate_records([record])
    except Exception:
        raise target.Rejected("invalid_stored_source") from None
    payload = target._canonical(record)
    if (hashlib.sha256(payload.encode("utf-8")).hexdigest() != ledger.get("payload_hash")
            or payload != ledger.get("source_payload")
            or ledger.get("name") != "avo-mv-centr-access-" + record["source_access_id"]
            or any(ledger.get(key) != record[key] for key in ("account", "source_access_id",
                "source_contact_id", "source_course_id", "source_snapshot_hash"))):
        raise target.Rejected("stored_source_fingerprint_mismatch")
    return record


def _decision(fr, ledger, now, excluded):
    record = _source(ledger)
    access = record["access"]
    result = {"record": record, "status": "Needs Review", "reason": None, "lessons": [],
              "missing_lesson_ids": [], "excluded_count": 0, "unavailable_count": 0}
    def stop(status, reason):
        result.update(status=status, reason=reason)
        return result
    if access["frozen"] is True:
        return stop("Frozen", "source_frozen")
    if access["frozen"] is not False:
        return stop("Needs Review", "source_freeze_unknown")
    if access["opens_at"]["kind"] != "datetime":
        return stop("Needs Review", "personal_start_unknown")
    start = target._instant(access["opens_at"]["iso"])
    end = None
    if access["closes_at"]["kind"] == "datetime":
        end = target._instant(access["closes_at"]["iso"])
        if end <= start:
            return stop("Needs Review", "personal_bounds_invalid")
    elif access["closes_at"]["kind"] != "unlimited":
        return stop("Needs Review", "personal_end_unknown")
    if end and now >= end:
        return stop("Expired", "source_personal_access_expired")
    mapped = target._mapped(record, target._mapping(fr, [record]))
    result["mapping"] = mapped
    if mapped["sync_status"] != "Stored":
        return stop(mapped["sync_status"], mapped["review_reason"])
    if any(ledger.get(key) and ledger.get(key) != mapped[key] for key in
           ("mapped_user", "mapped_contact", "mapped_course")):
        return stop("Needs Review", "target_mapping_changed")
    duplicates = fr.get_all(target.DOCTYPE, filters={"account": target.ACCOUNT,
        "source_contact_id": record["source_contact_id"], "source_course_id": record["source_course_id"]},
        fields=["name"], limit_page_length=2)
    if len(duplicates) != 1:
        return stop("Needs Review", "duplicate_source_access")
    eligible = []
    for lesson in record["lessons"]:
        if not (lesson["assigned"] is True and lesson["accessible"] is True and lesson["hidden"] is False):
            result["unavailable_count"] += 1
        elif lesson["id"] in excluded:
            result["excluded_count"] += 1
        else:
            eligible.append(lesson["id"])
    if not eligible:
        return stop("Needs Review", "no_recorded_available_lessons")
    rows = fr.get_all("Course Lesson", filters={"custom_avo_account": target.ACCOUNT,
        "custom_avo_id": ("in", eligible)}, fields=["name", "custom_avo_id", "course"], limit_page_length=0)
    by_id = {}
    for row in rows:
        ident = str(row["custom_avo_id"])
        if ident in by_id or row["course"] != mapped["mapped_course"]:
            return stop("Needs Review", "lesson_mapping_ambiguous_or_wrong_course")
        by_id[ident] = row["name"]
    result["missing_lesson_ids"] = [ident for ident in eligible if ident not in by_id]
    if result["missing_lesson_ids"]:
        return stop("Needs Review", "available_lesson_not_migrated")
    boundary = max(start, target._instant(access["as_of"] or record["captured_at"]))
    result.update(status="Ready", reason="recorded_availability_boundary", starts_at=target._site_time(access["opens_at"]["iso"]),
        ends_at=target._site_time(access["closes_at"]["iso"]) if end else None,
        opens_at=target._site_time(boundary.isoformat()), lessons=[by_id[ident] for ident in eligible])
    return result


def _excluded(values):
    result = set()
    for value in values:
        if type(value) is int: value = str(value)
        if not target._id(value): raise target.Rejected("invalid_excluded_lesson_id")
        result.add(value)
    return result


def _public(decision):
    record = decision["record"]
    return {"source_access_id": record["source_access_id"], "source_contact_id": record["source_contact_id"],
            "source_course_id": record["source_course_id"], "status": decision["status"], "reason": decision["reason"],
            "eligible_count": len(decision["lessons"]), "excluded_count": decision["excluded_count"],
            "unavailable_count": decision["unavailable_count"], "missing_lesson_ids": decision["missing_lesson_ids"]}


def preview_one(fr, ledger_name, *, allow_general_unlimited=False, excluded_lesson_ids=(), now=None):
    _check(fr, allow_general_unlimited)
    ledger = fr.get_doc(target.DOCTYPE, ledger_name)
    clock = target._instant(now) if now else datetime.now(timezone.utc)
    return _public(_decision(fr, ledger, clock, _excluded(excluded_lesson_ids)))


def _same(doc, values):
    for key, expected in values.items():
        if key == "doctype": continue
        actual = doc.get(key)
        if key == "lessons":
            if len(actual or []) != len(expected): return False
            if any(not _same(row, wanted) for row, wanted in zip(actual or [], expected)): return False
        elif key in DATE_KEYS and expected is not None:
            try:
                if datetime.fromisoformat(str(actual)) != datetime.fromisoformat(expected): return False
            except (ValueError, TypeError): return False
        elif expected is None:
            if actual not in (None, ""): return False
        elif actual != expected:
            return False
    return True


def _policy(fr, course, source_course_id, *, verify_only=False):
    name = "avo-mv-centr-policy-" + source_course_id
    policies = fr.get_all("LMS Access Policy", filters={"course": course}, fields=["name"], limit_page_length=2)
    expected = {"doctype": "LMS Access Policy", "course": course, **POLICY_VALUES}
    if policies:
        if len(policies) != 1 or policies[0]["name"] != name or not _same(fr.get_doc("LMS Access Policy", name), expected):
            raise target.Rejected("unmanaged_or_changed_course_policy")
    else:
        if verify_only:
            raise target.Rejected("unmanaged_or_changed_course_policy")
        if (fr.db.exists("LMS Enrollment", {"course": course})
                or fr.db.exists("LMS Access Grant", {"course": course}) or fr.db.exists("LMS Access Policy", name)):
            raise target.Rejected("course_contains_unmanaged_access")
        fr.get_doc(expected).insert(set_name=name)
    if not _same(fr.get_doc("LMS Access Policy", name), expected):
        raise target.Rejected("policy_readback_mismatch")


def _insert_or_verify(fr, name, values):
    doctype = values["doctype"]
    if not fr.db.exists(doctype, name):
        fr.get_doc(values).insert(set_name=name)
    if not _same(fr.get_doc(doctype, name), values):
        raise target.Rejected("native_access_readback_mismatch")


def _native_values(decision):
    record, mapping = decision["record"], decision["mapping"]
    user, course = mapping["mapped_user"], mapping["mapped_course"]
    grant_name = "avo-mv-centr-grant-" + record["source_access_id"]
    enrollment_name = "avo-mv-centr-enrollment-" + record["source_contact_id"] + "-" + record["source_course_id"]
    grant = {"doctype": "LMS Access Grant", "course": course, "member": user, "status": "Active",
        "frozen_at": None, "starts_at": decision["starts_at"], "personal_end_type": "At" if decision["ends_at"] else "Unlimited",
        "ends_at": decision["ends_at"], "personal_end_days": 0, "course_end_type": "Unlimited", "course_ends_at": None,
        "ignore_course_end": 0, "completed_retention_type": "None", "completed_retention_days": 0,
        "visited_retention_type": "None", "visited_retention_days": 0,
        "lessons": [{"lesson": lesson, "opening_type": "At", "opens_at": decision["opens_at"], "delay_days": 0,
            "prerequisite_state": "Satisfied", "manual_open": 0, "retain_when_limited": 0,
            "retention_end_type": "Unknown", "retention_ends_at": None} for lesson in decision["lessons"]]}
    enrollment = {"doctype": "LMS Enrollment", "course": course, "member": user,
                  "member_type": "Student", "role": "Member"}
    return grant_name, enrollment_name, grant, enrollment


def _verify_expired(fr, ledger, decision, excluded):
    """Verify a previous projection without inserting or changing native access."""
    if ledger.get("sync_status") not in ("Applied", "Expired"):
        raise target.Rejected("existing_native_references_require_review")
    end = target._instant(decision["record"]["access"]["closes_at"]["iso"])
    previous = _decision(fr, ledger, end - timedelta(microseconds=1), excluded)
    if previous["status"] != "Ready":
        raise target.Rejected("existing_native_references_require_review")
    grant_name, enrollment_name, grant, enrollment = _native_values(previous)
    if ledger.get("grant") != grant_name or ledger.get("enrollment") != enrollment_name:
        raise target.Rejected("ledger_native_reference_mismatch")
    course, user = previous["mapping"]["mapped_course"], previous["mapping"]["mapped_user"]
    if not fr.db.get_value("LMS Course", course, "name", for_update=True):
        raise target.Rejected("mapped_course_missing")
    _policy(fr, course, previous["record"]["source_course_id"], verify_only=True)
    for name, values in ((grant_name, grant), (enrollment_name, enrollment)):
        rows = fr.get_all(values["doctype"], filters={"course": course, "member": user},
                          fields=["name"], limit_page_length=2)
        if len(rows) != 1 or rows[0]["name"] != name:
            raise target.Rejected("unmanaged_native_access_pair")
        if not _same(fr.get_doc(values["doctype"], name), values):
            raise target.Rejected("native_access_readback_mismatch")


def apply_one(fr, ledger_name, *, allow_general_unlimited=False, duplicate_policy="defer",
              excluded_lesson_ids=(), now=None):
    """One atomic native projection; source snapshots and learning records stay intact."""
    _check(fr, allow_general_unlimited)
    if duplicate_policy != "defer": raise target.Rejected("duplicate_policy_not_supported")
    clock = target._instant(now) if now else datetime.now(timezone.utc)
    excluded = _excluded(excluded_lesson_ids)
    fr.db.begin()
    try:
        ledger = fr.get_doc(target.DOCTYPE, ledger_name, for_update=True)
        decision = _decision(fr, ledger, clock, excluded)
        if decision["status"] != "Ready":
            if ledger.get("grant") or ledger.get("enrollment"):
                if decision["status"] != "Expired":
                    raise target.Rejected("existing_native_references_require_review")
                _verify_expired(fr, ledger, decision, excluded)
            fr.db.set_value(target.DOCTYPE, ledger_name,
                {"sync_status": decision["status"], "review_reason": decision["reason"]})
            fr.db.commit()
            return _public(decision)
        record, mapping = decision["record"], decision["mapping"]
        user, course = mapping["mapped_user"], mapping["mapped_course"]
        # The standard enrollment model takes this same lock before duplication checks.
        if not fr.db.get_value("LMS Course", course, "name", for_update=True):
            raise target.Rejected("mapped_course_missing")
        _policy(fr, course, record["source_course_id"])
        grant_name, enrollment_name, grant, enrollment = _native_values(decision)
        for doctype, own_name in (("LMS Enrollment", enrollment_name), ("LMS Access Grant", grant_name)):
            rows = fr.get_all(doctype, filters={"course": course, "member": user}, fields=["name"], limit_page_length=2)
            if any(row["name"] != own_name for row in rows):
                raise target.Rejected("unmanaged_native_access_pair")
        if (ledger.get("grant") not in (None, "", grant_name)
                or ledger.get("enrollment") not in (None, "", enrollment_name)):
            raise target.Rejected("ledger_native_reference_mismatch")
        _insert_or_verify(fr, grant_name, grant)
        _insert_or_verify(fr, enrollment_name, enrollment)
        updates = {key: mapping[key] for key in ("mapped_user", "mapped_contact", "mapped_course")}
        updates.update(grant=grant_name, enrollment=enrollment_name, sync_status="Applied",
                       review_reason="recorded_unavailable_lessons_preserved" if decision["unavailable_count"] or decision["excluded_count"]
                       else "recorded_availability_boundary")
        fr.db.set_value(target.DOCTYPE, ledger_name, dict(updates))
        if not _same(fr.get_doc(target.DOCTYPE, ledger_name), updates):
            raise target.Rejected("activation_ledger_readback_mismatch")
        fr.db.commit()
        decision.update(status="Applied", reason=updates["review_reason"])
        return _public(decision)
    except Exception:
        fr.db.rollback()
        raise

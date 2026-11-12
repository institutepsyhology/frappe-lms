"""One MVC activation worker; a complete verified source ledger is mandatory."""
import argparse
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import re
import time

import activation
import target_sync as target
from run_store import event, save_state


EXPECTED = set(target.STATUSES.splitlines()) - {"Stored"}
RECORD_REJECTIONS = {"mapped_course_missing"}


def _code(exc):
    value = str(exc) if isinstance(exc, target.Rejected) else "record_validation_rejected"
    return value if re.fullmatch(r"[a-z_]{1,80}", value) else "unsafe_boundary_rejection"


def _class(exc):
    value = type(exc).__name__
    return value if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,79}", value) else "UnknownException"


def _verify_registry(fr, manifest):
    expected = manifest.get("payload", {}) if type(manifest) is dict else {}
    if (type(manifest) is not dict or manifest.get("account") != target.ACCOUNT
            or manifest.get("origin") != target.ORIGIN or type(manifest.get("record_count")) is not int
            or manifest["record_count"] < 1 or type(expected) is not dict
            or type(expected.get("aggregate_payload_hash")) is not str
            or not re.fullmatch(r"[0-9a-f]{64}", expected["aggregate_payload_hash"])):
        raise target.Rejected("invalid_source_manifest")
    rows = fr.get_all(target.DOCTYPE, filters={"account": target.ACCOUNT},
        fields=["source_access_id", "payload_hash"], order_by="source_access_id asc", limit_page_length=0)
    if not rows: raise target.Rejected("empty_source_ledger")
    digest, previous = hashlib.sha256(), None
    for row in rows:
        ident, fingerprint = row.get("source_access_id"), row.get("payload_hash")
        if (not target._id(ident) or previous is not None and ident <= previous
                or type(fingerprint) is not str or not re.fullmatch(r"[0-9a-f]{64}", fingerprint)):
            raise target.Rejected("source_registry_fingerprint_mismatch")
        digest.update((ident + ":" + fingerprint + "\n").encode("ascii")); previous = ident
    if len(rows) != manifest["record_count"] or digest.hexdigest() != expected["aggregate_payload_hash"]:
        raise target.Rejected("source_registry_fingerprint_mismatch")


def run(fr, manifest, state_path, events_path, *, allow_general_unlimited=False, excluded_lesson_ids=(), limit=None):
    state = {"status": "validating", "pid": os.getpid(), "processed": 0, "applied": 0,
        "already_applied": 0, "errors": 0, "consecutive_errors": 0, "statuses": {}, "reasons": {}}
    save_state(state_path, state)
    statuses, reasons = Counter(), Counter()
    def stop(exc, code=None):
        try: fr.db.rollback()
        except Exception: pass
        state.update(status="stopped", error=code or (_code(exc) if isinstance(exc, target.Rejected) else "unexpected_activation_failure"),
                     exception_class=_class(exc))
        save_state(state_path, state)
        event(events_path, status="stopped", code=state["error"], exception_class=_class(exc),
              processed=state["processed"], source_access_id=state.get("last_source_access_id"))
        raise target.Rejected(state["error"]) from None
    try:
        activation._check(fr, allow_general_unlimited)
        excluded = activation._excluded(excluded_lesson_ids)
        if limit is not None and (type(limit) is not int or limit < 1): raise target.Rejected("invalid_limit")
        _verify_registry(fr, manifest)
        state.update(status="running", expected=manifest["record_count"], source_registry_verified=True,
                     aggregate_payload_hash=manifest["payload"]["aggregate_payload_hash"])
        save_state(state_path, state)
        cursor, checkpoint = None, time.monotonic()
        finished = False
        while not finished:
            filters = {"account": target.ACCOUNT}
            if cursor is not None: filters["source_access_id"] = (">", cursor)
            rows = fr.get_all(target.DOCTYPE, filters=filters, fields=["name", "source_access_id", "sync_status"],
                              order_by="source_access_id asc", limit_page_length=500)
            if not rows: break
            for row in rows:
                ident = row.get("source_access_id")
                if (not target._id(ident) or cursor is not None and ident <= cursor
                        or row.get("name") != "avo-mv-centr-access-" + ident):
                    raise target.Rejected("source_registry_identity_mismatch")
                state.update(last_source_access_id=ident, processed=state["processed"] + 1)
                try:
                    result = activation.apply_one(fr, row["name"], allow_general_unlimited=True,
                                                  duplicate_policy="defer", excluded_lesson_ids=excluded)
                    if (type(result) is not dict or result.get("source_access_id") != ident
                            or result.get("status") not in EXPECTED
                            or type(result.get("reason")) is not str
                            or not re.fullmatch(r"[a-z_]{1,80}", result["reason"])):
                        raise target.Rejected("unexpected_activation_result")
                    status = result["status"]; statuses[status] += 1; reasons[result["reason"]] += 1
                    if status == "Applied": state["already_applied" if row.get("sync_status") == "Applied" else "applied"] += 1
                    state["consecutive_errors"] = 0
                except Exception as exc:
                    predictable = ((isinstance(exc, target.Rejected) and _code(exc) in RECORD_REJECTIONS)
                                   or type(exc) is getattr(fr, "ValidationError", None))
                    state["errors"] += 1
                    if not predictable:
                        state["write_outcome_unknown"] = not isinstance(exc, target.Rejected) or _code(exc) == "unexpected_activation_result"
                        stop(exc)
                    fr.db.rollback(); state["consecutive_errors"] += 1
                    event(events_path, status="record_rejected", source_access_id=ident,
                          code=_code(exc), exception_class=_class(exc))
                    if state["consecutive_errors"] >= 10: stop(exc, "consecutive_record_errors")
                state.update(statuses=dict(statuses), reasons=dict(reasons)); cursor = ident
                if state["errors"] and state["consecutive_errors"] or state["processed"] % 25 == 0 or time.monotonic() - checkpoint >= 10:
                    save_state(state_path, state); checkpoint = time.monotonic()
                    event(events_path, status="progress", processed=state["processed"], applied=state["applied"], already_applied=state["already_applied"])
                if limit is not None and state["processed"] >= limit: finished = True; break
        if limit is None and state["processed"] != state["expected"]:
            raise target.Rejected("activation_record_count_mismatch")
        # Frappe 16 rejects SQL function strings in SELECT. This bounded status
        # projection uses the same portable field contract as the source proof.
        counts = Counter(row["sync_status"] for row in fr.get_all(target.DOCTYPE,
            filters={"account": target.ACCOUNT}, fields=["sync_status"], limit_page_length=0))
        if any(status not in EXPECTED | {"Stored"} for status in counts):
            raise target.Rejected("invalid_ledger_status")
        state["live_counts"] = {"ledger_statuses": dict(counts),
            "native_grants": fr.db.count("LMS Access Grant", {"name": ("like", "avo-mv-centr-grant-%")}),
            "native_enrollments": fr.db.count("LMS Enrollment", {"name": ("like", "avo-mv-centr-enrollment-%")})}
        if sum(state["live_counts"]["ledger_statuses"].values()) != state["expected"]:
            raise target.Rejected("activation_ledger_count_changed")
        if limit is not None:
            state["status"] = "pilot_with_issues" if state["errors"] else "pilot_complete"
        else:
            state["status"] = "completed_with_issues" if state["errors"] else "completed"
        save_state(state_path, state); event(events_path, status=state["status"], processed=state["processed"], live_counts=state["live_counts"])
        return state
    except Exception as exc:
        if state["status"] == "stopped": raise
        stop(exc)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for flag in ("manifest", "state", "events"): parser.add_argument("--" + flag, type=Path, required=True)
    parser.add_argument("--allow-general-unlimited", action="store_true", required=True)
    parser.add_argument("--exclude-lesson", action="append", type=int, default=[])
    parser.add_argument("--limit", type=int)
    args = parser.parse_args()
    import fcntl
    import frappe
    with Path("/tmp/avo-mv-centr-activation.lock").open("a") as lock:
        os.chmod(lock.name, 0o600)
        try: fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print(json.dumps({"ok": False, "error": "activation_already_running"})); return 1
        running = False
        try:
            frappe.init(site=target.SITE); frappe.connect(); frappe.set_user("Administrator")
            manifest = json.loads(args.manifest.read_text(encoding="utf-8")); running = True
            result = run(frappe, manifest, args.state, args.events, allow_general_unlimited=args.allow_general_unlimited,
                         excluded_lesson_ids=args.exclude_lesson, limit=args.limit)
            print(json.dumps({"ok": True, "result": result}, ensure_ascii=True)); return 0
        except Exception as exc:
            if not running:
                save_state(args.state, {"status": "stopped", "pid": os.getpid(), "error": "activation_bootstrap_failed", "exception_class": _class(exc)})
                event(args.events, status="stopped", code="activation_bootstrap_failed", exception_class=_class(exc))
            print(json.dumps({"ok": False, "error": "activation_worker_stopped"})); return 1
        finally: frappe.destroy()


if __name__ == "__main__":
    raise SystemExit(main())

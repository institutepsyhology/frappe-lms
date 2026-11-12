import copy
from collections import Counter
import hashlib
import io
import json
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import run_activation as worker
import target_sync as target


class ValidationError(Exception):
    pass


class FakeDB:
    def __init__(self, app): self.app, self.rollbacks, self.snapshot = app, 0, None
    def begin(self): self.snapshot = copy.deepcopy(self.app.rows)
    def rollback(self):
        self.rollbacks += 1
        if self.snapshot is not None: self.app.rows = self.snapshot; self.snapshot = None
    def count(self, doctype, filters):
        return sum(row["sync_status"] == "Applied" for row in self.app.rows)


class FakeFrappe:
    ValidationError = ValidationError
    def __init__(self, size=2):
        self.local = SimpleNamespace(site=target.SITE)
        self.session = SimpleNamespace(user="Administrator")
        self.conf = {"individual_access_release_enabled": True}
        self.rows = [{"name": "avo-mv-centr-access-" + str(i), "source_access_id": str(i),
                      "payload_hash": hashlib.sha256(str(i).encode()).hexdigest(), "sync_status": "Stored"}
                     for i in range(1, size + 1)]
        self.db, self.queries, self.calls = FakeDB(self), [], []
    def get_all(self, doctype, **kwargs):
        self.queries.append((doctype, kwargs))
        rows = sorted(self.rows, key=lambda x: x["source_access_id"])
        if kwargs.get("group_by"):
            return [{"sync_status": key, "count": count} for key, count in Counter(x["sync_status"] for x in rows).items()]
        after = kwargs.get("filters", {}).get("source_access_id")
        if after: rows = [row for row in rows if row["source_access_id"] > after[1]]
        if kwargs.get("limit_page_length"): rows = rows[:kwargs["limit_page_length"]]
        return [{field: row[field] for field in kwargs["fields"]} for row in rows]
    def apply(self, fr, name, **kwargs):
        self.calls.append((name, kwargs))
        row = next(row for row in self.rows if row["name"] == name)
        row["sync_status"] = "Applied"
        return {"source_access_id": row["source_access_id"], "status": "Applied", "reason": "recorded_availability_boundary"}


def manifest(fr):
    digest = hashlib.sha256()
    for row in sorted(fr.rows, key=lambda x: x["source_access_id"]):
        digest.update((row["source_access_id"] + ":" + row["payload_hash"] + "\n").encode())
    return {"account": target.ACCOUNT, "origin": target.ORIGIN, "record_count": len(fr.rows),
            "payload": {"aggregate_payload_hash": digest.hexdigest()}}


class RunActivationTest(unittest.TestCase):
    def setUp(self):
        self.saved, self.events = [], []
        for name, callback in (("save_state", lambda path, value: self.saved.append(copy.deepcopy(value))),
                               ("event", lambda path, **value: self.events.append(copy.deepcopy(value)))):
            patcher = patch.object(worker, name, side_effect=callback)
            patcher.start(); self.addCleanup(patcher.stop)
    def run_worker(self, fr, *, callback=None, source_manifest=None, allow=True, **kwargs):
        with patch.object(worker.activation, "apply_one", side_effect=callback or fr.apply):
            return worker.run(fr, manifest(fr) if source_manifest is None else source_manifest,
                              "state.json", "events.jsonl", allow_general_unlimited=allow, **kwargs)

    def test_complete_run_counts_new_and_already_applied_and_live_records(self):
        fr = FakeFrappe(); fr.rows[0]["sync_status"] = "Applied"
        result = self.run_worker(fr, excluded_lesson_ids=[17, 23])
        self.assertEqual((result["status"], result["processed"], result["applied"], result["already_applied"]),
                         ("completed", 2, 1, 1))
        self.assertTrue(result["source_registry_verified"])
        self.assertEqual(result["live_counts"]["ledger_statuses"], {"Applied": 2})
        self.assertEqual(result["live_counts"]["native_grants"], 2)
        self.assertTrue(all(kwargs["allow_general_unlimited"] is True and kwargs["excluded_lesson_ids"] == {"17", "23"}
                            for _, kwargs in fr.calls))

    def test_expected_review_frozen_expired_and_pending_never_stop_on_ten(self):
        fr = FakeFrappe(35)
        statuses = ["Needs Review", "Frozen", "Expired", "Pending Contact", "Pending Course"]
        def apply(fr, name, **kwargs):
            row = next(x for x in fr.rows if x["name"] == name)
            status = statuses[(int(row["source_access_id"]) - 1) % len(statuses)]
            row["sync_status"] = status
            return {"source_access_id": row["source_access_id"], "status": status, "reason": "expected_pending"}
        result = self.run_worker(fr, callback=apply)
        self.assertEqual((result["status"], result["processed"], result["errors"], result["consecutive_errors"]),
                         ("completed", 35, 0, 0))

    def test_limit_is_processed_record_pilot_and_does_not_claim_completion(self):
        result = self.run_worker(FakeFrappe(4), limit=1)
        self.assertEqual((result["status"], result["processed"]), ("pilot_complete", 1))
        self.assertEqual(result["live_counts"]["ledger_statuses"], {"Applied": 1, "Stored": 3})

    def test_lexical_keyset_pagination_does_not_skip_or_repeat_records(self):
        fr = FakeFrappe(505)
        result = self.run_worker(fr)
        self.assertEqual((result["status"], result["processed"], result["applied"]), ("completed", 505, 505))
        names = [name for name, _ in fr.calls]
        self.assertEqual(len(set(names)), 505)
        pages = [kwargs for _, kwargs in fr.queries if kwargs.get("fields") == ["name", "source_access_id", "sync_status"]]
        self.assertEqual(len(pages), 3)
        self.assertTrue(all(page["limit_page_length"] == 500 for page in pages))

    def test_cli_requires_manifest_and_explicit_unlimited_optin(self):
        variants = [["worker", "--state", "state", "--events", "events", "--allow-general-unlimited"],
                    ["worker", "--state", "state", "--events", "events", "--manifest", "manifest"]]
        for arguments in variants:
            with self.subTest(arguments=arguments), patch.object(sys, "argv", arguments), \
                 patch("sys.stderr", new_callable=io.StringIO), self.assertRaises(SystemExit) as stopped:
                worker.main()
            self.assertEqual(stopped.exception.code, 2)
        self.assertEqual(self.saved, [])

    def test_wrong_site_role_release_or_missing_optin_prevent_queries_and_apply(self):
        variants = [("site", "my-lk.iomp.ru"), ("role", "Other"), ("release", False), ("allow", False)]
        for kind, value in variants:
            with self.subTest(kind=kind):
                fr = FakeFrappe()
                if kind == "site": fr.local.site = value
                if kind == "role": fr.session.user = value
                if kind == "release": fr.conf["individual_access_release_enabled"] = value
                with self.assertRaises(target.Rejected): self.run_worker(fr, allow=kind != "allow")
                self.assertEqual(fr.queries, []); self.assertEqual(fr.calls, [])
                self.assertEqual(self.saved[-1]["status"], "stopped")

    def test_partial_or_changed_manifest_registry_stops_before_first_native_write(self):
        fr = FakeFrappe(); source = manifest(fr)
        for changed in ({**source, "record_count": 3}, {**source, "account": "mastervision"},
                        {**source, "payload": {"aggregate_payload_hash": "f" * 64}}):
            with self.subTest(changed=changed), self.assertRaises(target.Rejected):
                self.run_worker(fr, source_manifest=changed)
            self.assertEqual(fr.calls, [])
            self.assertEqual(self.saved[-1]["processed"], 0)

    def test_empty_registry_fails_even_if_manifest_is_otherwise_valid(self):
        with self.assertRaisesRegex(target.Rejected, "empty_source_ledger"):
            self.run_worker(FakeFrappe(0), source_manifest={**manifest(FakeFrappe(0)), "record_count": 1})

    def test_validation_errors_are_safe_and_stop_at_ten_consecutive(self):
        fr = FakeFrappe(20)
        def bad(*args, **kwargs): raise ValidationError("secret@example.test and private telephone")
        with self.assertRaisesRegex(target.Rejected, "consecutive_record_errors"):
            self.run_worker(fr, callback=bad)
        self.assertEqual((self.saved[-1]["processed"], self.saved[-1]["errors"]), (10, 10))
        self.assertNotIn("secret@", json.dumps(self.saved + self.events))
        self.assertEqual(self.events[-1]["exception_class"], "ValidationError")

    def test_expected_result_resets_error_streak(self):
        fr = FakeFrappe(20); calls = []
        def sometimes(fr, name, **kwargs):
            calls.append(name)
            if len(calls) not in (10, 20): raise ValidationError("private validation details")
            row = next(x for x in fr.rows if x["name"] == name)
            row["sync_status"] = "Needs Review"
            return {"source_access_id": row["source_access_id"], "status": "Needs Review", "reason": "expected_pending"}
        result = self.run_worker(fr, callback=sometimes)
        self.assertEqual((result["status"], result["errors"], result["consecutive_errors"]), ("completed_with_issues", 18, 0))

    def test_one_predictable_error_then_success_finishes_with_issues(self):
        fr = FakeFrappe(); attempts = []
        def once(fr, name, **kwargs):
            attempts.append(name)
            if len(attempts) == 1: raise ValidationError("private validation details")
            return fr.apply(fr, name, **kwargs)
        result = self.run_worker(fr, callback=once)
        self.assertEqual((result["status"], result["processed"], result["errors"], result["applied"]),
                         ("completed_with_issues", 2, 1, 1))
        self.assertEqual(result["live_counts"]["ledger_statuses"], {"Stored": 1, "Applied": 1})
        self.assertEqual([x["source_access_id"] for x in self.events if x["status"] == "record_rejected"], ["1"])

    def test_pilot_with_predictable_error_does_not_claim_clean_completion(self):
        def bad(*args, **kwargs): raise ValidationError("private validation details")
        result = self.run_worker(FakeFrappe(), callback=bad, limit=1)
        self.assertEqual((result["status"], result["processed"], result["errors"]), ("pilot_with_issues", 1, 1))

    def test_fingerprint_policy_and_unknown_rejections_stop_immediately(self):
        for error in (target.Rejected("stored_source_fingerprint_mismatch"),
                      target.Rejected("unmanaged_or_changed_course_policy"), target.Rejected("private@value")):
            fr = FakeFrappe(20)
            with self.subTest(error=type(error).__name__), self.assertRaises(target.Rejected):
                self.run_worker(fr, callback=lambda *args, **kwargs: (_ for _ in ()).throw(error))
            self.assertEqual(self.saved[-1]["processed"], 1)
            self.assertNotIn("private@", json.dumps(self.saved + self.events))

    def test_unexpected_callback_failure_rolls_back_and_records_unknown_outcome(self):
        fr = FakeFrappe()
        def bad(fr, name, **kwargs):
            fr.db.begin(); fr.rows[0]["sync_status"] = "Applied"
            raise RuntimeError("private database connection details")
        with self.assertRaisesRegex(target.Rejected, "unexpected_activation_failure"):
            self.run_worker(fr, callback=bad)
        self.assertEqual(fr.rows[0]["sync_status"], "Stored")
        self.assertTrue(self.saved[-1]["write_outcome_unknown"])
        self.assertGreater(fr.db.rollbacks, 0)
        self.assertNotIn("private database", json.dumps(self.saved + self.events))

    def test_changed_result_shape_stops_as_unknown_native_outcome(self):
        def bad(fr, name, **kwargs):
            return {"source_access_id": name.rsplit("-", 1)[1], "status": "Ready", "reason": "unexpected"}
        with self.assertRaisesRegex(target.Rejected, "unexpected_activation_result"):
            self.run_worker(FakeFrappe(), callback=bad)
        self.assertTrue(self.saved[-1]["write_outcome_unknown"])


if __name__ == "__main__":
    unittest.main()

"""Worker checks with in-memory gzip, journals and synthetic Frappe tables."""
import copy
import gzip
import hashlib
import io
import json
import unittest
from datetime import timedelta, timezone
from unittest.mock import patch

import run_store as worker
import target_sync as target
from test_target_sync import FakeFrappe, record


class WorkerFrappe(FakeFrappe):
    def get_all(self, doctype, **kwargs):
        rows = super().get_all(doctype, **kwargs)
        if kwargs.get("order_by") == "source_access_id asc":
            rows.sort(key=lambda row: row["source_access_id"])
        return rows


class WorkerTest(unittest.TestCase):
    def setUp(self):
        self.app = WorkerFrappe().mapped()
        self.states, self.events = [], []
        self.records = [record("101"), record("102")]
        self.manifest, self.compressed = self.payload(self.records)
        self.patches = [
            patch.object(target, "ZoneInfo", return_value=timezone(timedelta(hours=3))),
            patch.object(worker, "digest_file", side_effect=lambda path: hashlib.sha256(self.compressed).hexdigest()),
            patch.object(worker.gzip, "open", side_effect=lambda *args, **kwargs: io.StringIO(gzip.decompress(self.compressed).decode("utf-8"))),
            patch.object(worker, "save_state", side_effect=lambda path, state: self.states.append(copy.deepcopy(state))),
            patch.object(worker, "event", side_effect=lambda path, **value: self.events.append(copy.deepcopy(value))),
        ]
        for replacement in self.patches:
            replacement.start(); self.addCleanup(replacement.stop)

    @staticmethod
    def payload(records):
        body = "".join(target._canonical(row) + "\n" for row in records).encode("utf-8")
        compressed = gzip.compress(body, mtime=0)
        rolling = hashlib.sha256()
        for row in records:
            digest = hashlib.sha256(target._canonical(row).encode("utf-8")).hexdigest()
            rolling.update((row["source_access_id"] + ":" + digest + "\n").encode("ascii"))
        return ({"account": target.ACCOUNT, "origin": target.ORIGIN, "record_count": len(records),
                 "lesson_count": sum(len(row["lessons"]) for row in records),
                 "payload": {"compressed_sha256": hashlib.sha256(compressed).hexdigest(),
                             "aggregate_payload_hash": rolling.hexdigest()}}, compressed)

    def run_worker(self, limit=None):
        return worker.run(self.app, "private-payload.gz", self.manifest,
                          "private-state.json", "private-events.jsonl", limit=limit)

    def test_completed_run_verifies_source_target_counts_and_hash(self):
        result = self.run_worker()
        self.assertEqual(result["status"], "completed")
        self.assertEqual((result["processed"], result["stored"], result["already_stored"]), (2, 2, 0))
        self.assertEqual(result["lesson_count"], 2)
        self.assertEqual(result["aggregate_payload_hash"], self.manifest["payload"]["aggregate_payload_hash"])
        self.assertTrue(result["target_verified"])
        self.assertEqual(self.states[-1], result)
        self.assertEqual([value["status"] for value in self.events], ["batch_verified", "completed"])
        self.assertFalse(self.app.tables["LMS Access Grant"])
        self.assertFalse(self.app.tables["LMS Enrollment"])

    def test_replay_uses_ledger_as_checkpoint_without_duplicate_writes(self):
        self.run_worker()
        result = self.run_worker()
        self.assertEqual(result["status"], "completed")
        self.assertEqual((result["stored"], result["already_stored"]), (0, 2))
        self.assertEqual(len(self.app.tables[target.DOCTYPE]), 2)
        self.assertEqual(self.app.bulk_calls, 1)

    def test_pilot_stops_at_limit_without_claiming_full_target_verification(self):
        result = self.run_worker(limit=1)
        self.assertEqual(result["status"], "pilot_complete")
        self.assertEqual((result["processed"], result["expected"]), (1, 2))
        self.assertNotIn("target_verified", result)
        self.assertNotIn("aggregate_payload_hash", result)
        self.assertEqual(set(self.app.tables[target.DOCTYPE]), {"avo-mv-centr-access-101"})
        self.assertEqual([value["status"] for value in self.events], ["batch_verified"])

    def test_identity_compressed_hash_and_invalid_count_manifest_fail_before_schema(self):
        variants = []
        for key, value in (("account", "iomp"), ("origin", "https://shop.iomp.ru"),
                           ("record_count", True), ("record_count", 0)):
            candidate = copy.deepcopy(self.manifest); candidate[key] = value; variants.append(candidate)
        candidate = copy.deepcopy(self.manifest)
        candidate["payload"]["compressed_sha256"] = "f" * 64; variants.append(candidate)
        for candidate in variants:
            with self.subTest(candidate=candidate), patch.object(target, "ensure_schema") as schema:
                with self.assertRaisesRegex(target.Rejected, "payload_manifest_mismatch"):
                    worker.run(self.app, "payload.gz", candidate, "state", "events")
                schema.assert_not_called()
        self.assertEqual(self.app.bulk_calls, 0)
        self.assertTrue(all(state["processed"] == 0 for state in self.states))
        self.assertEqual(self.states[-1]["status"], "stopped")

    def test_manifest_fingerprints_and_totals_are_checked_before_schema_or_write(self):
        variants = []
        for key, value in (("record_count", 3), ("lesson_count", 3)):
            candidate = copy.deepcopy(self.manifest); candidate[key] = value; variants.append(candidate)
        candidate = copy.deepcopy(self.manifest)
        candidate["payload"]["aggregate_payload_hash"] = "f" * 64; variants.append(candidate)
        for candidate in variants:
            with self.subTest(candidate=candidate), patch.object(target, "ensure_schema") as schema, \
                    patch.object(target, "store_batch") as store:
                with self.assertRaises(target.Rejected):
                    worker.run(self.app, "payload.gz", candidate, "state", "events")
                schema.assert_not_called()
                store.assert_not_called()

    def test_strange_manifest_types_fail_with_safe_code_before_schema(self):
        variants = [None, [], "unexpected", {**self.manifest, "payload": []},
                    {**self.manifest, "payload": None}]
        for candidate in variants:
            with self.subTest(kind=type(candidate).__name__), patch.object(target, "ensure_schema") as schema:
                with self.assertRaisesRegex(target.Rejected, "payload_manifest_mismatch"):
                    worker.run(self.app, "payload.gz", candidate, "state", "events")
                schema.assert_not_called()

    def test_target_fingerprint_mismatch_persists_stopped_status(self):
        original = self.app.get_all
        def tampered(doctype, **kwargs):
            result = original(doctype, **kwargs)
            if doctype == target.DOCTYPE and kwargs.get("fields") == ["source_access_id", "payload_hash"]:
                result[0]["payload_hash"] = "f" * 64
            return result
        with patch.object(self.app, "get_all", side_effect=tampered), \
                self.assertRaisesRegex(target.Rejected, "final_target_fingerprint_mismatch"):
            self.run_worker()
        self.assertEqual(self.states[-1]["status"], "stopped")
        self.assertEqual(self.states[-1]["error"], "final_target_fingerprint_mismatch")
        self.assertEqual(self.events[-1]["status"], "stopped")
        self.assertFalse(any(event["status"] == "completed" for event in self.events))

    def test_unexpected_store_failure_is_safe_and_never_acknowledges_batch(self):
        private_error = "DO NOT PRINT private names or source values"
        with patch.object(target, "store_batch", side_effect=RuntimeError(private_error)), \
                self.assertRaisesRegex(target.Rejected, "^unexpected_worker_failure$"):
            self.run_worker()
        self.assertEqual(self.states[-1]["status"], "stopped")
        self.assertEqual(self.states[-1]["processed"], 0)
        self.assertEqual([event["status"] for event in self.events], ["stopped"])
        self.assertNotIn(private_error, json.dumps(self.states + self.events))
        self.assertFalse(self.app.tables[target.DOCTYPE])

    def test_duplicate_or_out_of_lexical_order_source_ids_are_stopped(self):
        for records in ([record("101"), record("101")], [record("102"), record("101")]):
            self.manifest, self.compressed = self.payload(records)
            with self.subTest(ids=[r["source_access_id"] for r in records]), \
                    self.assertRaisesRegex(target.Rejected, "payload_order_or_duplicate"):
                self.run_worker()
            self.assertEqual(self.app.bulk_calls, 0)
            self.assertFalse(any(event["status"] == "batch_verified" for event in self.events))
            self.assertEqual(self.states[-1]["status"], "stopped")

    def test_source_ids_follow_archive_lexical_not_numeric_order(self):
        self.manifest, self.compressed = self.payload([record("1"), record("10"), record("2")])
        result = self.run_worker()
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["processed"], 3)

    def test_invalid_limit_fails_before_schema(self):
        for limit in (True, 0, -1, "1"):
            with self.subTest(limit=limit), patch.object(target, "ensure_schema") as schema, \
                    self.assertRaisesRegex(target.Rejected, "invalid_limit"):
                self.run_worker(limit=limit)
            schema.assert_not_called()


if __name__ == "__main__": unittest.main()

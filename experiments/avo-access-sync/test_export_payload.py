import copy
import gzip
import hashlib
import json
from pathlib import Path
import sqlite3
import unittest
from unittest.mock import patch
import uuid

import export_payload as exporter
from test_source_archive import access, lesson


def record(ident="1", contact="101", course="11"):
    item = lesson()
    return {"schema_version": 1, "account": "mv-centr", "origin": exporter.ORIGIN,
            "source_access_id": ident, "source_contact_id": contact, "source_course_id": course,
            "source_snapshot_hash": "a" * 64, "captured_at": "2026-10-13T08:16:00.864000Z",
            "access": access(), "lessons": [{k: str(v) if k == "id" else v for k, v in item.items()
                                              if k not in ("title", "raw")} ]}


class ExportPayloadTest(unittest.TestCase):
    def setUp(self):
        # Workspace fixtures avoid the Windows default-temp permission issue.
        self.folder = Path(__file__).resolve().parent / "test-artifacts" / uuid.uuid4().hex
        self.folder.mkdir(parents=True)
        self.addCleanup(self.cleanup)
        self.archive = self.folder / "archive.sqlite"
        self.archive.write_bytes(b"synthetic archive")
        self.output = self.folder / "access.jsonl.gz"
        self.manifest = self.folder / "manifest.json"
        self.records = [record(), record("2")]
        self.scope = {"verified_scope_records": 2, "excluded_contact_records": 0,
                      "excluded_course_records": 0, "excluded_overlap_records": 0,
                      "expected_export_records": 2}

    def cleanup(self):
        for item in self.folder.iterdir():
            item.unlink()
        self.folder.rmdir()

    def export(self, records=None, **kwargs):
        rows = iter(self.records if records is None else records)
        with patch.object(exporter, "_scope_counts", return_value=self.scope), \
             patch.object(exporter, "iter_records", return_value=rows) as source:
            manifest = exporter.export_archive(self.archive, self.output, self.manifest, **kwargs)
        return manifest, source

    def test_private_manifest_counts_hashes_and_canonical_gzip_readback(self):
        manifest, _ = self.export()
        self.assertEqual(manifest, json.loads(self.manifest.read_text(encoding="utf-8")))
        expected = b"".join(exporter.canonical(row) + b"\n" for row in self.records)
        self.assertEqual(gzip.decompress(self.output.read_bytes()), expected)
        self.assertEqual(manifest["payload"]["uncompressed_sha256"], hashlib.sha256(expected).hexdigest())
        self.assertEqual(manifest["payload"]["compressed_sha256"], hashlib.sha256(self.output.read_bytes()).hexdigest())
        hashes = b"".join(row["source_access_id"].encode() + b":" + hashlib.sha256(exporter.canonical(row)).hexdigest().encode() + b"\n" for row in self.records)
        self.assertEqual(manifest["payload"]["aggregate_payload_hash"], hashlib.sha256(hashes).hexdigest())
        self.assertEqual((manifest["record_count"], manifest["lesson_count"]), (2, 2))
        self.assertEqual(manifest["duplicate_contact_course_pairs"], [["101", "11", 2]])
        self.assertEqual(manifest["additional_access_link_count"], 1)
        self.assertEqual(manifest["counts"]["contact_email_status"], "not_available_in_relationship_archive")
        self.assertNotIn("Must never", self.manifest.read_text())

    def test_common_exclusions_are_forwarded_once_and_manifest_stores_only_hash(self):
        manifest, source = self.export(excluded_contact_ids=(x for x in (900001, 900002)), excluded_course_ids={999})
        self.assertEqual(source.call_args.args[1:], ({"900001", "900002"}, {"999"}))
        self.assertEqual(manifest["exclusions"]["contacts"]["count"], 2)
        self.assertNotIn("900001", self.manifest.read_text())

    def test_existing_destination_is_never_overwritten(self):
        for target in (self.output, self.manifest):
            with self.subTest(target=target.name):
                target.write_text("existing")
                with self.assertRaisesRegex(exporter.SafeCode, "destination_exists"):
                    self.export()
                self.assertEqual(target.read_text(), "existing")
                target.unlink()

    def test_race_creating_destination_is_preserved(self):
        publish = exporter._publish
        def raced(temporary, destination):
            destination.write_text("concurrent file")
            publish(temporary, destination)
        with patch.object(exporter, "_publish", side_effect=raced):
            with self.assertRaisesRegex(exporter.SafeCode, "destination_exists"):
                self.export()
        self.assertEqual(self.output.read_text(), "concurrent file")
        self.assertFalse(self.manifest.exists())
        self.assertFalse(list(self.folder.glob("*.tmp")))

    def test_manifest_race_rolls_back_only_our_new_payload(self):
        publish = exporter._publish
        def raced(temporary, destination):
            if destination == self.manifest:
                destination.write_text("concurrent manifest")
            publish(temporary, destination)
        with patch.object(exporter, "_publish", side_effect=raced):
            with self.assertRaisesRegex(exporter.SafeCode, "destination_exists"):
                self.export()
        self.assertFalse(self.output.exists())
        self.assertEqual(self.manifest.read_text(), "concurrent manifest")

    def test_stream_failure_and_count_mismatch_leave_no_partial_outputs(self):
        def failing():
            yield self.records[0]
            raise exporter.SafeCode("invalid_source_structure")
        for rows, message in ((failing(), "invalid_source_structure"), ([self.records[0]], "export_count_mismatch")):
            with self.subTest(message=message), self.assertRaisesRegex(exporter.SafeCode, message):
                self.export(rows)
            self.assertFalse(self.output.exists())
            self.assertFalse(self.manifest.exists())
            self.assertFalse(list(self.folder.glob("*.tmp")))

    def test_source_change_is_detected_before_publication(self):
        def changing():
            yield from self.records
            self.archive.write_bytes(b"changed source archive bytes")
        with self.assertRaisesRegex(exporter.SafeCode, "archive_changed_during_export"):
            self.export(changing())
        self.assertFalse(self.output.exists())
        self.assertFalse(self.manifest.exists())

    def test_payload_bytes_are_reproducible_and_unknown_flags_remain_unknown(self):
        self.records[1]["access"]["frozen"] = None
        first, _ = self.export()
        original = self.output.read_bytes()
        self.output.unlink(); self.manifest.unlink()
        second, _ = self.export()
        self.assertEqual(self.output.read_bytes(), original)
        self.assertEqual(second["counts"]["frozen"], {"false": 1, "unknown": 1})
        self.assertEqual(first["source_scope"]["historical_snapshot_date"], "2026-10-13")

    def test_source_scope_counts_include_exclusion_overlap_and_exclude_foreign(self):
        self.archive.unlink()
        db = sqlite3.connect(self.archive)
        db.executescript("""CREATE TABLE latest(namespace TEXT,link_key TEXT,snapshot_id INTEGER,successful INTEGER);
          CREATE TABLE snapshots(id INTEGER PRIMARY KEY,successful INTEGER);
          CREATE TABLE course_access(snapshot_id INTEGER PRIMARY KEY,contact_id TEXT,course_id TEXT);""")
        rows = [(1, "101", "11"), (2, "101", "12"), (3, "102", "12"), (4, "102", "11"),
                (446462, "103", "13"), (100998, "103", "13")]
        for ident, contact, course in rows:
            db.execute("INSERT INTO latest VALUES(?,?,?,1)", (exporter.ORIGIN, str(ident), ident))
            db.execute("INSERT INTO snapshots VALUES(?,1)", (ident,))
            db.execute("INSERT INTO course_access VALUES(?,?,?)", (ident, contact, course))
        db.commit(); db.close()
        self.assertEqual(exporter._scope_counts(self.archive, {"101"}, {"12"}),
                         {"verified_scope_records": 4, "excluded_contact_records": 2,
                          "excluded_course_records": 2, "excluded_overlap_records": 1,
                          "expected_export_records": 1})


if __name__ == "__main__":
    unittest.main()

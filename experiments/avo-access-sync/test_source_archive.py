import hashlib
import json
import sqlite3
import unittest
from pathlib import Path
from unittest.mock import patch

import source_archive as reader


def date(kind="unknown", raw=None, iso=None):
    return {"raw": raw, "iso": iso, "kind": kind}


def access():
    return {"opens_at": date("datetime", "2020-01-02 03:04:05", "2020-01-02T03:04:05+03:00"),
            "closes_at": date("unlimited", "9999-12-31 00:00:00"),
            "report_check_ends_at": date("unset", "0000-00-00 00:00:00"),
            "training_start_at": date("unset", ""), "effective_closes_at": date(),
            "frozen": False, "ignore_course_end": False, "day_access_shift": 0,
            "personal_term": "unlimited", "derived_status": "unknown",
            "as_of": "2026-10-13T08:16:00.864Z"}


def lesson(ident=26, **changes):
    return {"id": ident, "assigned": True, "accessible": False, "hidden": False,
            "day_access": 0, "number": 0, "can_edit_accessible": False,
            "title": "Must never be exported", "raw": {}, **changes}


class SourceArchiveTest(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(":memory:")
        self.addCleanup(self.db.close)
        self.db.executescript("""
          CREATE TABLE latest(namespace TEXT,link_key TEXT,snapshot_id INTEGER,
            observation_id INTEGER,successful INTEGER,PRIMARY KEY(namespace,link_key));
          CREATE TABLE snapshots(id INTEGER PRIMARY KEY,content_sha256 TEXT,
            record_json TEXT,successful INTEGER);
          CREATE TABLE observations(id INTEGER PRIMARY KEY,captured_at TEXT);
          CREATE TABLE course_access(snapshot_id INTEGER PRIMARY KEY,contact_id TEXT,
            course_id TEXT,access_json TEXT);
          CREATE TABLE lessons(snapshot_id INTEGER,ordinal INTEGER,lesson_id TEXT,
            lesson_json TEXT,PRIMARY KEY(snapshot_id,ordinal));
        """)

    def add(self, ident=300, *, snapshot=None, origin=reader.ORIGIN, contact="101",
            course="11", settings=None, lessons=None, captured="2026-10-13T11:16:00.864+03:00",
            digest="a" * 64, success=1):
        snapshot = snapshot or ident
        raw = json.dumps({"link_id": ident, "contact": {"id": contact}, "course": {"id": course},
                          "source": {"captured_at": "2026-10-13T08:17:00Z"}})
        self.db.execute("INSERT INTO snapshots VALUES(?,?,?,?)", (snapshot, digest, raw, success))
        self.db.execute("INSERT INTO observations VALUES(?,?)", (snapshot, captured))
        self.db.execute("INSERT INTO course_access VALUES(?,?,?,?)",
                        (snapshot, contact, course, json.dumps(access() if settings is None else settings)))
        self.db.execute("INSERT OR REPLACE INTO latest VALUES(?,?,?,?,?)",
                        (origin, str(ident), snapshot, snapshot, success))
        for ordinal, item in enumerate([lesson()] if lessons is None else lessons):
            self.db.execute("INSERT INTO lessons VALUES(?,?,?,?)",
                            (snapshot, ordinal, str(item.get("id")), json.dumps(item)))
        return raw

    def test_normalized_contract_has_no_profile_titles_or_raw_objects(self):
        self.add()
        row, = reader.iter_records(self.db)
        self.assertEqual(set(row), {"schema_version", "account", "origin", "source_access_id",
                                   "source_contact_id", "source_course_id", "source_snapshot_hash",
                                   "captured_at", "access", "lessons"})
        self.assertEqual((row["source_access_id"], row["source_contact_id"], row["source_course_id"]),
                         ("300", "101", "11"))
        self.assertEqual(row["captured_at"], "2026-10-13T08:16:00.864000Z")
        self.assertEqual(row["access"], access())
        self.assertEqual(row["lessons"], [{"id": "26", "assigned": True, "accessible": False,
                                         "hidden": False, "day_access": 0, "number": 0,
                                         "can_edit_accessible": False}])
        self.assertNotIn("Must never", json.dumps(row))

    def test_latest_successful_snapshot_and_confirmed_mvc_range_only(self):
        self.add(1, snapshot=10)
        self.add(1, snapshot=11, contact="102")
        self.add(2, success=0)
        self.add(3, origin="https://shop.mastervision.su")
        self.add(446462)
        self.add(100998)
        rows = list(reader.iter_records(self.db))
        self.assertEqual([(x["source_access_id"], x["source_contact_id"]) for x in rows], [("1", "102")])

    def test_private_exclusions_and_multiple_links_preserve_source_identity(self):
        self.add(1); self.add(2); self.add(3, contact="103"); self.add(4, course="12")
        rows = list(reader.iter_records(self.db, excluded_contact_ids={103}, excluded_course_ids={12}))
        self.assertEqual([x["source_access_id"] for x in rows], ["1", "2"])
        for value in (True, 0, "001", -1):
            with self.subTest(value=value), self.assertRaises(reader.SafeCode):
                list(reader.iter_records(self.db, excluded_contact_ids=[value]))

    def test_null_unknown_and_independent_lesson_flags_are_preserved(self):
        settings = access(); settings.update(frozen=None, ignore_course_end=None, day_access_shift=None, as_of=None)
        self.add(settings=settings, lessons=[lesson(assigned=None, hidden=True, accessible=False,
                                                   day_access=None, number=None, can_edit_accessible=None)])
        row, = reader.iter_records(self.db)
        self.assertEqual(row["access"], settings)
        self.assertIsNone(row["lessons"][0]["assigned"])
        self.assertTrue(row["lessons"][0]["hidden"])
        self.assertFalse(row["lessons"][0]["accessible"])

    def test_hash_and_capture_fallback_fetch_only_one_raw_snapshot(self):
        raw = self.add(digest=None, captured=None)
        statements = []; self.db.set_trace_callback(statements.append)
        row, = reader.iter_records(self.db)
        self.assertEqual(row["source_snapshot_hash"], hashlib.sha256(raw.encode()).hexdigest())
        self.assertEqual(row["captured_at"], "2026-10-13T08:17:00Z")
        self.assertEqual(sum("SELECT record_json" in s for s in statements), 1)

    def test_normal_iteration_never_fetches_raw_snapshot_or_writes(self):
        self.add(1); self.add(2)
        statements = []; self.db.set_trace_callback(statements.append)
        iterator = reader.iter_records(self.db)
        first = next(iterator)
        self.assertEqual(first["source_access_id"], "1")
        self.assertFalse(any("record_json" in x for x in statements))
        self.assertFalse(any("snapshot_id=2" in x.replace(" ", "") for x in statements))
        self.assertTrue(all(x.lstrip().upper().startswith("SELECT") for x in statements))
        iterator.close()

    def test_date_and_source_timing_are_preserved_without_current_decisions(self):
        settings = access()
        settings["training_start_at"] = date("datetime", "2020-03-01 00:00:00", "2020-03-01T00:00:00+03:00")
        settings["closes_at"] = date("invalid", "bad source date")
        settings["day_access_shift"] = -3
        self.add(settings=settings, lessons=[lesson(day_access=87)])
        row, = reader.iter_records(self.db)
        self.assertEqual(row["access"], settings)
        self.assertEqual(row["lessons"][0]["day_access"], 87)

    def test_unknown_access_structure_and_strange_types_fail_with_safe_codes(self):
        bad = [[], {**access(), "new_rule": 7}, {**access(), "frozen": 1},
               {**access(), "day_access_shift": True},
               {**access(), "opens_at": date("datetime", "source", "2020-01-01T00:00:00")},
               {**access(), "opens_at": {"raw": None, "iso": None, "kind": "mystery"}}]
        for index, settings in enumerate(bad):
            with self.subTest(settings=settings):
                self.db.execute("DELETE FROM latest")
                self.add(index + 1, settings=settings)
                with self.assertRaises(reader.SafeCode) as raised:
                    list(reader.iter_records(self.db))
                self.assertRegex(str(raised.exception), "^[a-z_]+$")

    def test_path_database_is_opened_in_readonly_mode(self):
        self.add()
        with patch.object(reader.sqlite3, "connect", return_value=self.db) as connect:
            row, = reader.iter_records(Path("synthetic-archive.sqlite"))
        self.assertEqual(row["source_access_id"], "300")
        self.assertTrue(connect.call_args.args[0].endswith("synthetic-archive.sqlite?mode=ro"))
        self.assertEqual(connect.call_args.kwargs, {"uri": True})

    def test_capture_fallback_uses_as_of_without_substituting_today(self):
        self.add(captured=None)
        self.db.execute("UPDATE snapshots SET record_json=?", (json.dumps({"source": {}}),))
        row, = reader.iter_records(self.db)
        self.assertEqual(row["captured_at"], "2026-10-13T08:16:00.864000Z")
        self.db.execute("UPDATE course_access SET access_json=?", (json.dumps({**access(), "as_of": None}),))
        with self.assertRaisesRegex(reader.SafeCode, "missing_capture_time"):
            list(reader.iter_records(self.db))

    def test_lesson_ids_and_strange_boolean_types_cannot_silently_change_access(self):
        for items in ([lesson(assigned=1)], [lesson(26), lesson(26)], [lesson(id=True)],
                      [lesson(new_permission=True)]):
            with self.subTest(items=items):
                self.db.execute("DELETE FROM latest"); self.db.execute("DELETE FROM lessons")
                self.db.execute("DELETE FROM snapshots"); self.db.execute("DELETE FROM course_access")
                self.db.execute("DELETE FROM observations")
                self.add(lessons=items)
                with self.assertRaises(reader.SafeCode):
                    list(reader.iter_records(self.db))


if __name__ == "__main__":
    unittest.main()

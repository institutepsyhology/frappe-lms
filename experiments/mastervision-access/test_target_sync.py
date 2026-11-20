import hashlib
import importlib.util
import json
from datetime import datetime
from pathlib import Path
import sqlite3
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch
import zlib

from target_archive import ACCOUNT, BOUND, FIVE_CONTROL, FIVE_LESSONS, ORIGIN, Review, complete_archive, config_reader, latest, project
from target_sync import course_plan


def blobs(v):
    return zlib.compress(json.dumps(v).encode())


def at(value):
    return {"kind": "datetime", "iso": value}


DATE = "2026-03-05T17:18:09+03:00"
NOW = "2026-11-20T12:00:00Z"
RULES = {"course_id": 598, "end_at": {"kind": "unlimited"}, "starts_at": None, "draft_lesson_ids": [],
         "permanent_lesson_access": False, "access_notice_content": None, "show_when_unavailable": 1}


def detail(ids, end=DATE, frozen=False):
    return {"course": {"id": 598, "end_at": {"kind": "unknown"}},
            "availableLessons": [{"id": i, "accessible": 1, "hidden": False} for i in ids],
            "access": {"opens_at": at("2026-02-09T15:56:04+03:00"),
                       "closes_at": at(end) if end else {"kind": "unlimited"},
                       "frozen": frozen, "ignore_course_end": False}}


class Fixture:
    def setUp(self):
        with tempfile.NamedTemporaryFile(dir=Path.cwd(), suffix=".sqlite", delete=False) as tmp:
            self.path = Path(tmp.name)
        self.addCleanup(self.path.unlink)
        self.db = sqlite3.connect(self.path)
        self.addCleanup(self.db.close)
        self.db.row_factory = sqlite3.Row
        self.db.executescript("""
        CREATE TABLE metadata(key TEXT PRIMARY KEY,value TEXT);
        CREATE TABLE configs(sha TEXT PRIMARY KEY, payload BLOB);
        CREATE TABLE cards(link_id INTEGER PRIMARY KEY, contact_id INTEGER, course_id INTEGER,
                           captured_at TEXT, config_sha TEXT REFERENCES configs(sha),detail BLOB);
        CREATE TABLE inventory(link_id INTEGER PRIMARY KEY);
        CREATE TABLE missing(link_id INTEGER PRIMARY KEY);
        CREATE TABLE problems(link_id INTEGER PRIMARY KEY);
        """)
        self.db.executemany("INSERT INTO metadata VALUES (?,?)", {
            "account": ACCOUNT, "origin": ORIGIN, "capture_state": "complete", "schema": "1",
            "through": str(BOUND), "scope": "inventory", "started_at": NOW, "completed_at": NOW}.items())
        self.lesson_config = [{"id": lid, "day_access": 0, "hidden": False, "accessible": 1}
                              for lid in sorted(set(FIVE_LESSONS) | {6519, 6520})]
        blob = blobs(self.lesson_config)
        self.sha = hashlib.sha256(zlib.decompress(blob)).hexdigest()
        self.db.execute("insert into configs values (?,?)", (self.sha, blob))
        self.add(1, 53, [6518, 6519], None)
        self.add(446462, 53, [6518])
        self.add(FIVE_CONTROL, 54, FIVE_LESSONS, None)
        self.add(BOUND, 55, [], None, course=600)
        self.db.commit()

    def add(self, link, contact, lessons, end=DATE, *, course=598):
        d = detail(lessons, end)
        d["course"]["id"] = course
        if link == FIVE_CONTROL:
            d["access"]["opens_at"] = at("2026-10-27T18:04:00+03:00")
        self.db.execute("insert into inventory values(?)", (link,))
        self.db.execute("insert into cards values(?,?,?,?,?,?)",
                        (link, contact, course, NOW, self.sha, blobs(d)))


class ArchiveTests(Fixture, unittest.TestCase):
    def test_newest_only_replaces_more_permissive_older_and_preserves_five(self):
        with complete_archive(self.path) as db:
            read = config_reader(db)
            winner, five = latest(db, 598)
            self.assertEqual(winner["link_id"], 446462)
            grant, _, allowed = project(winner, read(self.sha), RULES)
            self.assertEqual(allowed, (6518,))
            self.assertEqual(grant["ends_at"], "2026-03-05 17:18:09")
            self.assertEqual(grant["personal_end_type"], "At")
            self.assertEqual(grant["completed_retention_type"], "None")
            self.assertEqual(grant["visited_retention_type"], "None")
            grant, _, allowed = project(five, read(self.sha), RULES)
            self.assertEqual(grant["personal_end_type"], "Unlimited")
            self.assertEqual(allowed, FIVE_LESSONS)

    def test_course_editor_can_restrict_an_assigned_lesson(self):
        row = next(latest(self.db, 598))
        cfg = config_reader(self.db)(self.sha)
        rule = {"day_access": 0, "request_report": 0, "check_report": 0, "start_date": "2099-01-01 08:00:00"}
        with self.assertRaisesRegex(Review, "future_lesson_requires_schedule"):
            project(row, cfg, {**RULES, "lesson_rules": {"6518": rule}})
        with self.assertRaisesRegex(Review, "report_prerequisites_need_history"):
            project(row, cfg, {**RULES, "lesson_rules": {"6519": {**rule, "check_report": 1}}})

    def test_archive_must_be_complete_and_match_terminal_inventory(self):
        for statement in ("UPDATE metadata SET value='collecting' WHERE key='capture_state'",
                          "INSERT INTO inventory VALUES (333)", "INSERT INTO problems VALUES (1)",
                          "UPDATE metadata SET value='another' WHERE key='origin'"):
            with self.subTest(statement=statement):
                backup = sqlite3.connect(":memory:")
                self.db.backup(backup)
                try:
                    self.db.execute(statement)
                    self.db.commit()
                    with self.assertRaises(Review), complete_archive(self.path):
                        self.fail()
                finally:
                    backup.backup(self.db)
                    backup.close()

    def test_drafts_and_omitted_never_become_grants(self):
        row = next(latest(self.db, 598))
        grant, _, allowed = project(row, config_reader(self.db)(self.sha), {**RULES, "draft_lesson_ids": [6518]})
        self.assertEqual(allowed, ())
        self.assertEqual(grant["personal_end_type"], "At")

    def test_global_term_freeze_and_hide(self):
        d = detail([6519, 6520], None, frozen=True)
        d["availableLessons"][0]["hidden"] = True
        row = {"detail": blobs(d), "course_id": 598, "captured_at": NOW}
        grant, _, allowed = project(row, config_reader(self.db)(self.sha), {**RULES, "end_at": at(DATE)})
        self.assertEqual(allowed, (6520,))
        self.assertEqual(grant["status"], "Frozen")
        self.assertEqual((grant["course_end_type"], grant["course_ends_at"]), ("At", "2026-03-05 17:18:09"))

    def test_unrecognized_dates_and_ids_never_fall_back_to_fully_open(self):
        for d in (detail([999]), {**detail([6518]), "access": {**detail([])["access"], "closes_at": {"kind": "unknown"}}}):
            with self.assertRaises(Review):
                project({"detail": blobs(d), "course_id": 598, "captured_at": NOW}, config_reader(self.db)(self.sha), RULES)

    def test_hash_of_configuration_read_back(self):
        self.db.execute("UPDATE configs SET payload=?", (blobs([]),))
        with self.assertRaisesRegex(Review, "hash"):
            config_reader(self.db)(self.sha)


class Doc(dict):
    def __getattr__(self, key):
        return self.get(key)


class Fake:
    def __init__(self):
        self.db = self
        self.tables = {}

    def exists(self, dt, name):
        if isinstance(name, dict):
            return bool(self.get_all(dt, filters=name, fields=["name"], limit_page_length=1))
        return (dt, name) in self.tables

    def get_all(self, dt, *, filters, fields, limit_page_length):
        found = []
        for (kind, name), doc in self.tables.items():
            if kind != dt:
                continue
            for key, matcher in filters.items():
                if isinstance(matcher, tuple):
                    if doc.get(key) not in matcher[1]:
                        break
                elif doc.get(key) != matcher:
                    break
            else:
                found.append({f: doc.get(f) for f in fields})
        return found

    def get_doc(self, dt, name=None, for_update=False):
        if name:
            return self.tables[dt, name]
        values = Doc(dt)
        def insert(set_name):
            values["name"] = set_name
            self.tables[values["doctype"], set_name] = values
        values.insert = insert
        return values


class WriteTests(Fixture, unittest.TestCase):
    def fixture(self):
        fr = Fake()
        for dt, name, v in [
                ("LMS Course","c",{"custom_avo_id":"598","custom_lms_id":"598","published":0,
                                    "disable_self_learning":1, "show_when_unavailable":1}),
                ("User","u",{"custom_avo_contact_id":"53","enabled":1}), ("Contact","k",{"custom_avo_contact_id":"53","user":"u"}),
                ("Course Lesson","l",{"course":"c","custom_avo_id":"6518","custom_lms_id":"6518","is_draft":0,
                                      "include_in_preview":0,"publication_audience":"All"})]:
            fr.tables[dt,name] = Doc(name=name, custom_avo_account=ACCOUNT, **v)
        return fr

    def test_native_contact_uses_a_unique_user_link_and_rejects_conflicting_claims(self):
        from target_sync import members
        fr = self.fixture()
        card = fr.tables["Contact", "k"]
        card.update(custom_avo_account=None, custom_avo_contact_id=None)
        self.assertEqual(members(fr, [53]), {53: "u"})
        fr.tables["Contact", "other"] = Doc(name="other", user="another",
            custom_avo_account=ACCOUNT, custom_avo_contact_id="53")
        self.assertEqual(members(fr, [53]), {})
        fr.tables["Contact", "other"].update(user="u", custom_avo_account=None, custom_avo_contact_id=None)
        self.assertEqual(members(fr, [53]), {})
        del fr.tables["Contact", "other"]
        card.update(custom_avo_account="iomp", custom_avo_contact_id="53")
        self.assertEqual(members(fr, [53]), {})

    def test_projection_idempotent_and_conflicting_access_is_held(self):
        fr = self.fixture()
        def apply(write, rules=RULES):
            return course_plan(fr, self.db, 598, rules, config_reader(self.db), write=write, omitted=set())
        original = len(fr.tables)
        self.assertEqual(apply(False)["new_grants"], 1)
        self.assertEqual(len(fr.tables), original)
        self.assertEqual(apply(True)["pending_contact"], 1)
        self.assertEqual(apply(True)["new_grants"], 0)
        saved = fr.tables["LMS Access Grant","avo-mastervision-grant-446462"]
        self.assertEqual(saved["source_reference"], "mastervision:contacttraining:446462")
        self.assertEqual(saved["lessons"][0]["lesson"], "l")
        self.assertEqual(saved["lessons"][0]["retain_when_limited"], 0)
        saved["personal_end_type"] = "Unlimited"
        with self.assertRaisesRegex(Review, "existing_record_changed"):
            apply(True)

    def test_bounded_application_checks_concurrent_access_before_first_policy(self):
        fr = self.fixture()
        batch = [next(latest(self.db, 598))]
        def execute():
            return course_plan(fr, self.db, 598, RULES, config_reader(self.db), write=True, omitted=set(), batch=batch)
        fr.tables["LMS Enrollment","before"] = Doc(name="before", course="c", member="unrelated")
        with self.assertRaisesRegex(Review, "course_access_changed"):
            execute()
        del fr.tables["LMS Enrollment","before"]
        self.assertEqual(execute()["new_grants"], 1)
        self.assertEqual(execute()["new_grants"], 0)

    def test_unmapped_lesson_holds_only_its_whole_personal_link(self):
        fr = self.fixture()
        fr.tables["User","v"] = Doc(name="v", custom_avo_account=ACCOUNT, custom_avo_contact_id="54", enabled=1)
        fr.tables["Contact","c2"] = Doc(name="c2", custom_avo_account=ACCOUNT, custom_avo_contact_id="54",user="v")
        counts = course_plan(fr, self.db, 598, RULES, config_reader(self.db), write=True, omitted=set())
        self.assertEqual((counts["mapped"], counts["pending_relation"]), (1, 1))
        self.assertFalse(fr.exists("LMS Access Grant", "avo-mastervision-grant-446809"))
        self.assertTrue(fr.exists("LMS Access Grant", "avo-mastervision-grant-446462"))

    def test_ambiguous_mapping_history_and_existing_manual_enrollment(self):
        fr = self.fixture()
        def preview(settings):
            return course_plan(fr, self.db, 598, settings, config_reader(self.db), write=False, omitted=set())
        with self.assertRaisesRegex(Review, "completed_lesson_history"):
            preview({**RULES, "permanent_lesson_access": True})
        fr.tables["Contact","k"]["user"] = "other"
        self.assertEqual(preview(RULES)["pending_contact"], 2)
        fr.tables["LMS Enrollment","manual"] = Doc(name="manual", course="c", member="u")
        with self.assertRaisesRegex(Review, "unmanaged"):
            preview(RULES)

    def test_existing_authored_notice_is_preserved(self):
        fr = self.fixture()
        authored = {"blocks":[{"type":"paragraph","data":{"text":"original notice"}}]}
        fr.tables["LMS Course","c"]["access_notice_content"] = json.dumps(authored)
        with self.assertRaisesRegex(Review, "existing_course_notice_differs"):
            course_plan(fr, self.db, 598, RULES, config_reader(self.db), write=True, omitted=set())
        self.assertEqual(json.loads(fr.tables["LMS Course","c"]["access_notice_content"]), authored)

    def test_installed_decision_code_denies_expired_renewal_and_only_allows_five_assigned(self):
        fr = self.fixture()
        for dt, name, extra in (("Contact", "k2", {"user":"u2"}), ("User", "u2", {"enabled":1})):
            fr.tables[dt,name] = Doc(name=name, custom_avo_account=ACCOUNT, custom_avo_contact_id="54", **extra)
        for lid in (6519, *FIVE_LESSONS[1:]):
            fr.tables["Course Lesson",str(lid)] = Doc(**{**fr.tables["Course Lesson","l"], "name":str(lid),
                        "custom_avo_id":str(lid), "custom_lms_id":str(lid)})
        course_plan(fr, self.db, 598, RULES, config_reader(self.db), write=True, omitted=set())
        for (dt, name), grant in list(fr.tables.items()):
            if dt == "LMS Access Grant":
                for item in grant["lessons"]:
                    key = name + item["lesson"]
                    fr.tables["LMS Access Grant Lesson",key] = Doc(**item, name=key, parent=name,
                                                 parenttype=dt, parentfield="lessons")
        def lookup(dt, where, fields, **kwargs):
            fields = [fields] if isinstance(fields, str) else fields
            where = where if isinstance(where, dict) else {"name":where}
            found = fr.get_all(dt, filters=where, fields=fields, limit_page_length=1)
            if not found:
                return None
            return Doc(found[0]) if kwargs.get("as_dict") else found[0][fields[0]]
        def find(dt, filters, fields=None, pluck=None):
            records = fr.get_all(dt, filters=filters, fields=fields or [pluck], limit_page_length=0)
            return [r[pluck] for r in records] if pluck else [Doc(r) for r in records]
        frappe = SimpleNamespace(conf={"individual_access_release_enabled":True},
                     db=SimpleNamespace(get_value=lookup,get_all=find,exists=fr.exists))
        utils = SimpleNamespace(get_datetime=lambda v: v if isinstance(v,datetime) else datetime.fromisoformat(v),
                                now_datetime=lambda: datetime(2026,11,20,15))
        access_blocks = SimpleNamespace(is_blocked=lambda *args: False)
        path = Path(__file__).resolve().parents[2] / "lms/lms/individual_access.py"
        spec = importlib.util.spec_from_file_location("checked_access_reader", path)
        native = importlib.util.module_from_spec(spec)
        with patch.dict("sys.modules",{"frappe":frappe,"frappe.utils":utils,"lms.lms.access_blocks":access_blocks}):
            spec.loader.exec_module(native)
            self.assertFalse(native.restrict_member_lesson(course="c", lesson="l", user="u", enrolled=True))
            self.assertFalse(native.restrict_member_lesson(course="c", lesson="6519", user="u2", enrolled=True))
            for name in ("l", *(str(lid) for lid in FIVE_LESSONS[1:])):
                self.assertTrue(native.restrict_member_lesson(course="c", lesson=name, user="u2", enrolled=True))
                self.assertFalse(native.restrict_member_lesson(course="c", lesson=name, user="guest", enrolled=False))


if __name__ == "__main__":
    unittest.main()

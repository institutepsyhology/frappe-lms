import copy
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import activation
import target_sync as target
from test_target_sync import FakeFrappe, Row, record, date


NOW = "2026-11-12T12:00:00Z"
LEDGER = "avo-mv-centr-access-101"


class NativeDoc(dict):
    def __init__(self, app, values):
        super().__init__(copy.deepcopy(values))
        object.__setattr__(self, "app", app)

    def insert(self, *, set_name):
        self["name"] = set_name
        doctype = self["doctype"]
        if set_name in self.app.tables[doctype]: raise RuntimeError("duplicate")
        if doctype == "LMS Enrollment":
            assert self.app.conf["individual_access_release_enabled"] is True
            policies = self.app.get_all("LMS Access Policy", filters={"course": self["course"]})
            assert len(policies) == 1 and policies[0]["enabled"] == 1
        if doctype == self.app.corrupt_native:
            self["status"] = "corrupted"
        self.app.inserted.append(doctype)
        self.app.tables[doctype][set_name] = Row(copy.deepcopy(dict(self)))
        return self


class App(FakeFrappe):
    def __init__(self):
        super().__init__()
        self.inserted = []
        self.corrupt_native = None
        self.course_locks = 0

    def get_doc(self, value, name=None, **kwargs):
        return NativeDoc(self, value if isinstance(value, dict) else self.tables[value][name])

    def get_value(self, doctype, name, field, **kwargs):
        if kwargs.get("for_update") and doctype == "LMS Course": self.course_locks += 1
        return self.tables[doctype].get(name, {}).get(field)


class ActivationTest(unittest.TestCase):
    def setUp(self):
        tz = patch.object(target, "ZoneInfo", return_value=timezone(timedelta(hours=3)))
        tz.start(); self.addCleanup(tz.stop)
        self.app = App().mapped()
        self.app.tables["Course Lesson"]["lesson-401"] = Row(name="lesson-401", doctype="Course Lesson",
            custom_avo_account=target.ACCOUNT, custom_avo_id="401", course="course-internal", is_draft=1)

    def prepare(self, source=None):
        source = record() if source is None else source
        target.store_batch(self.app, [source])
        return source

    def apply(self, **kwargs):
        return activation.apply_one(self.app, LEDGER, allow_general_unlimited=True, now=NOW, **kwargs)

    def ledger(self): return self.app.tables[target.DOCTYPE][LEDGER]

    def test_restores_only_recorded_available_lessons_after_snapshot_without_publishing(self):
        source = record()
        source["lessons"] += [{**source["lessons"][0], "id": "402", "accessible": False},
                              {**source["lessons"][0], "id": "403", "hidden": True},
                              {**source["lessons"][0], "id": "404", "assigned": False}]
        self.prepare(source)
        course = copy.deepcopy(self.app.tables["LMS Course"]["course-internal"])
        result = self.apply()
        self.assertEqual(result["status"], "Applied")
        grant = self.app.tables["LMS Access Grant"]["avo-mv-centr-grant-101"]
        self.assertEqual(grant["starts_at"], "2020-01-01 12:00:00")
        self.assertEqual(grant["course_end_type"], "Unlimited")
        self.assertEqual(grant["personal_end_type"], "Unlimited")
        self.assertEqual(grant["lessons"][0]["opens_at"], "2026-10-13 11:16:00.864000")
        self.assertEqual([(row["lesson"], row["manual_open"], row["prerequisite_state"])
                          for row in grant["lessons"]], [("lesson-401", 0, "Satisfied")])
        self.assertEqual(grant["completed_retention_type"], "None")
        self.assertEqual(grant["visited_retention_type"], "None")
        self.assertEqual(self.app.tables["LMS Course"]["course-internal"], course)
        self.assertEqual(self.app.tables["Course Lesson"]["lesson-401"]["is_draft"], 1)
        self.assertEqual(self.app.inserted, ["LMS Access Policy", "LMS Access Grant", "LMS Enrollment"])
        self.assertEqual(self.ledger()["source_payload"], target._canonical(source))
        self.assertEqual(result["unavailable_count"], 3)

    def test_authorization_and_release_switch_fail_before_transaction(self):
        self.prepare()
        with self.assertRaisesRegex(target.Rejected, "general_unlimited_not_authorized"):
            activation.apply_one(self.app, LEDGER, now=NOW)
        for flag in (False, "true", 1):
            self.app.conf["individual_access_release_enabled"] = flag
            with self.assertRaisesRegex(target.Rejected, "individual_access_release_disabled"): self.apply()
        self.app.conf["individual_access_release_enabled"] = True
        for surface, key, value in ((self.app.local, "site", "my-lk.iomp.ru"),
                                    (self.app.session, "user", "ordinary-user")):
            previous = getattr(surface, key); setattr(surface, key, value)
            with self.assertRaises(target.Rejected): self.apply()
            setattr(surface, key, previous)
        self.assertEqual(self.app.inserted, [])

    def test_frozen_unknown_freeze_and_expired_source_never_enroll(self):
        for frozen, closes, status in ((True, date("unlimited"), "Frozen"),
                                      (None, date("unlimited"), "Needs Review"),
                                      (False, date(value="2026-11-01T00:00:00+03:00"), "Expired")):
            app = self.app = App().mapped()
            source = record(); source["access"].update(frozen=frozen, closes_at=closes)
            self.prepare(source)
            self.assertEqual(self.apply()["status"], status)
            self.assertEqual(self.ledger()["sync_status"], status)
            self.assertFalse(app.tables["LMS Enrollment"])
            self.assertFalse(app.tables["LMS Access Grant"])
            self.assertFalse(app.tables["LMS Access Policy"])

    def test_personal_finite_end_and_future_start_are_preserved(self):
        source = record()
        source["access"].update(opens_at=date(value="2030-01-01T00:00:00+03:00"),
                                closes_at=date(value="2031-01-01T00:00:00+03:00"), personal_term="until_date")
        self.prepare(source); self.apply()
        grant = self.app.tables["LMS Access Grant"]["avo-mv-centr-grant-101"]
        self.assertEqual(grant["starts_at"], "2030-01-01 00:00:00")
        self.assertEqual(grant["ends_at"], "2031-01-01 00:00:00")
        self.assertEqual(grant["personal_end_type"], "At")
        self.assertEqual(grant["lessons"][0]["opens_at"], grant["starts_at"])

    def test_unknown_personal_end_and_invalid_bounds_defer(self):
        for closes, reason in ((date("unknown"), "personal_end_unknown"),
                               (date(value="2019-01-01T00:00:00+03:00"), "personal_bounds_invalid")):
            self.app = App().mapped()
            source = record(); source["access"]["closes_at"] = closes
            self.prepare(source)
            self.assertEqual(self.apply()["reason"], reason)
            self.assertFalse(self.app.tables["LMS Enrollment"])

    def test_missing_allowed_lesson_defers_but_explicit_content_exclusion_can_omit_it(self):
        source = record(); source["lessons"].append({**source["lessons"][0], "id": "402"})
        self.prepare(source)
        result = self.apply()
        self.assertEqual(result["status"], "Needs Review")
        self.assertEqual(result["missing_lesson_ids"], ["402"])
        self.assertFalse(self.app.tables["LMS Enrollment"])
        result = self.apply(excluded_lesson_ids={402})
        self.assertEqual((result["status"], result["excluded_count"]), ("Applied", 1))
        self.assertEqual(len(self.app.tables["LMS Access Grant"]["avo-mv-centr-grant-101"]["lessons"]), 1)

    def test_lessons_from_another_course_or_account_are_never_used(self):
        self.prepare()
        row = self.app.tables["Course Lesson"]["lesson-401"]
        row["course"] = "other-course"
        self.assertEqual(self.apply()["reason"], "lesson_mapping_ambiguous_or_wrong_course")
        row["course"] = "course-internal"; row["custom_avo_account"] = "iomp"
        self.assertEqual(self.apply()["reason"], "available_lesson_not_migrated")
        self.assertFalse(self.app.tables["LMS Access Grant"])

    def test_contact_only_disabled_and_stale_user_mappings_defer(self):
        self.prepare()
        self.app.tables["User"]["user-private-key"]["enabled"] = 0
        self.assertEqual(self.apply()["reason"], "user_disabled")
        self.app.tables["User"].clear()
        self.app.tables["Contact"]["contact"] = Row(name="contact", custom_avo_account=target.ACCOUNT,
            custom_avo_contact_id="201", user=None)
        self.assertEqual(self.apply()["status"], "Pending Contact")
        self.assertFalse(self.app.tables["LMS Enrollment"])

    def test_duplicate_source_relations_are_preserved_without_activation(self):
        self.prepare()
        target.store_batch(self.app, [record("102")])
        self.assertEqual(self.apply()["reason"], "duplicate_source_access")
        self.assertEqual(len(self.app.tables[target.DOCTYPE]), 2)
        self.assertFalse(self.app.tables["LMS Enrollment"])

    def test_existing_unmanaged_policy_or_access_prevents_opt_in(self):
        self.prepare()
        self.app.tables["LMS Enrollment"]["native"] = Row(name="native", course="course-internal", member="other")
        with self.assertRaisesRegex(target.Rejected, "course_contains_unmanaged_access"): self.apply()
        self.app.tables["LMS Enrollment"].clear()
        self.app.tables["LMS Access Policy"]["native-policy"] = Row(name="native-policy", course="course-internal")
        with self.assertRaisesRegex(target.Rejected, "unmanaged_or_changed_course_policy"): self.apply()
        self.assertEqual(self.ledger()["sync_status"], "Stored")

    def test_idempotent_native_readback_preserves_learning_progress_and_rejects_changed_grant(self):
        self.prepare(); self.apply()
        enrollment = self.app.tables["LMS Enrollment"]["avo-mv-centr-enrollment-201-301"]
        enrollment["progress"] = 42
        self.apply()
        self.assertEqual(self.app.inserted.count("LMS Enrollment"), 1)
        self.assertEqual(self.app.inserted.count("LMS Access Grant"), 1)
        self.assertEqual(enrollment["progress"], 42)
        self.app.tables["LMS Access Grant"]["avo-mv-centr-grant-101"]["personal_end_type"] = "Unknown"
        with self.assertRaisesRegex(target.Rejected, "native_access_readback_mismatch"): self.apply()

    def test_applied_access_becomes_expired_on_clock_change_without_native_writes(self):
        source = record()
        source["access"].update(closes_at=date(value="2026-11-13T00:00:00+03:00"), personal_term="until_date")
        self.prepare(source); self.apply()
        references = {key: self.ledger()[key] for key in ("grant", "enrollment")}
        before = {doctype: copy.deepcopy(self.app.tables[doctype])
                  for doctype in ("LMS Access Policy", "LMS Access Grant", "LMS Enrollment")}
        inserted = list(self.app.inserted)
        for clock in ("2026-11-14T12:00:00Z", "2026-11-15T12:00:00Z"):
            result = activation.apply_one(self.app, LEDGER, allow_general_unlimited=True, now=clock)
            self.assertEqual(result["status"], "Expired")
            self.assertEqual(self.ledger()["sync_status"], "Expired")
            self.assertEqual({key: self.ledger()[key] for key in references}, references)
            self.assertEqual(self.app.inserted, inserted)
            self.assertEqual({doctype: self.app.tables[doctype] for doctype in before}, before)

    def test_tampered_native_end_cannot_be_relabelled_as_normally_expired(self):
        source = record()
        source["access"].update(closes_at=date(value="2026-11-13T00:00:00+03:00"), personal_term="until_date")
        self.prepare(source); self.apply()
        self.app.tables["LMS Access Grant"]["avo-mv-centr-grant-101"]["ends_at"] = "2031-01-01 00:00:00"
        with self.assertRaisesRegex(target.Rejected, "native_access_readback_mismatch"):
            activation.apply_one(self.app, LEDGER, allow_general_unlimited=True, now="2026-11-14T12:00:00Z")
        self.assertEqual(self.ledger()["sync_status"], "Applied")
        self.assertEqual(self.app.tables["LMS Access Grant"]["avo-mv-centr-grant-101"]["ends_at"], "2031-01-01 00:00:00")

    def test_expired_verification_never_recreates_a_missing_owned_policy(self):
        source = record()
        source["access"].update(closes_at=date(value="2026-11-13T00:00:00+03:00"), personal_term="until_date")
        self.prepare(source); self.apply()
        self.app.tables["LMS Access Policy"].clear()
        inserted = list(self.app.inserted)
        with self.assertRaisesRegex(target.Rejected, "unmanaged_or_changed_course_policy"):
            activation.apply_one(self.app, LEDGER, allow_general_unlimited=True, now="2026-11-14T12:00:00Z")
        self.assertFalse(self.app.tables["LMS Access Policy"])
        self.assertEqual(self.app.inserted, inserted)
        self.assertEqual(self.ledger()["sync_status"], "Applied")

    def test_native_readback_failure_rolls_back_policy_grant_enrollment_and_ledger(self):
        self.prepare()
        self.app.corrupt_native = "LMS Access Grant"
        with self.assertRaisesRegex(target.Rejected, "native_access_readback_mismatch"): self.apply()
        self.assertFalse(self.app.tables["LMS Access Policy"])
        self.assertFalse(self.app.tables["LMS Access Grant"])
        self.assertFalse(self.app.tables["LMS Enrollment"])
        self.assertEqual(self.ledger()["sync_status"], "Stored")

    def test_hash_mismatch_and_no_eligible_lessons_never_create_access(self):
        self.prepare()
        self.ledger()["payload_hash"] = "b" * 64
        with self.assertRaisesRegex(target.Rejected, "stored_source_fingerprint_mismatch"): self.apply()
        self.app = App().mapped()
        source = record(); source["lessons"][0]["accessible"] = False
        self.prepare(source)
        self.assertEqual(self.apply()["reason"], "no_recorded_available_lessons")
        self.assertFalse(self.app.tables["LMS Enrollment"])

    def test_preview_is_counts_and_ids_only_with_no_mutation(self):
        self.prepare()
        before = copy.deepcopy(self.app.tables)
        result = activation.preview_one(self.app, LEDGER, allow_general_unlimited=True, now=NOW)
        self.assertEqual(result["status"], "Ready")
        self.assertEqual(self.app.tables, before)
        self.assertNotIn("user-private-key", str(result))
        self.assertNotIn("course-internal", str(result))

    def test_frappe_set_value_mutation_does_not_expand_expected_readback_fields(self):
        self.prepare()
        original = self.app.set_value
        def framework_set_value(doctype, name, values):
            values["modified"] = "2026-11-12 15:00:00"
            original(doctype, name, values)
            self.app.tables[doctype][name]["modified"] = datetime.fromisoformat(values["modified"])
        with patch.object(self.app, "set_value", side_effect=framework_set_value):
            result = self.apply()
        self.assertEqual(result["status"], "Applied")
        self.assertEqual(self.ledger()["sync_status"], "Applied")
        self.assertIsInstance(self.ledger()["modified"], datetime)


if __name__ == "__main__": unittest.main()

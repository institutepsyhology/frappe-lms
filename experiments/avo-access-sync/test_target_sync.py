import copy
import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import patch

import target_sync as target


class Row(dict):
    __getattr__ = dict.get
    __setattr__ = dict.__setitem__


def date(kind="datetime", value="2020-01-01T12:00:00+03:00"):
    return {"raw": value, "iso": value if kind == "datetime" else None, "kind": kind}


def record(ident="101", contact="201", course="301"):
    return {"schema_version": 1, "account": target.ACCOUNT, "origin": target.ORIGIN,
            "source_access_id": ident, "source_contact_id": contact, "source_course_id": course,
            "source_snapshot_hash": "a" * 64, "captured_at": "2026-10-13T08:16:00.864Z",
            "access": {"opens_at": date(), "closes_at": date("unlimited"),
                       "report_check_ends_at": date("unset"), "training_start_at": date("unset"),
                       "effective_closes_at": date("unknown"), "frozen": False, "ignore_course_end": False,
                       "day_access_shift": 0, "personal_term": "unlimited", "derived_status": "unknown",
                       "as_of": "2026-10-13T08:16:00.864Z"},
            "lessons": [{"id": "401", "assigned": True, "accessible": True, "hidden": False,
                         "day_access": 0, "number": 1, "can_edit_accessible": True}]}


class FakeDoc(Row):
    def __init__(self, app, values):
        super().__init__(copy.deepcopy(values))
        object.__setattr__(self, "app", app)

    def insert(self, set_name=None, **kwargs):
        doctype = self["doctype"]
        self["name"] = set_name or self.get("name") or "new-document"
        self.setdefault("owner", "Administrator")
        if self["name"] in self.app.tables[doctype]:
            raise RuntimeError("duplicate")
        self.app.tables[doctype][self["name"]] = Row(copy.deepcopy(dict(self)))
        return self

    def save(self, **kwargs):
        self.app.tables[self["doctype"]][self["name"]] = Row(copy.deepcopy(dict(self)))
        return self


class FakeFrappe:
    def __init__(self):
        self.local = SimpleNamespace(site=target.SITE)
        self.session = SimpleNamespace(user="Administrator")
        self.conf = {"individual_access_release_enabled": True}
        self.tables = {key: {} for key in ("DocType", "User", "Contact", "LMS Course", "Course Lesson",
                      target.DOCTYPE, "LMS Access Grant", "LMS Enrollment", "LMS Access Policy")}
        self.tables["DocType"][target.DOCTYPE] = Row(doctype="DocType", name=target.DOCTYPE,
            custom=1, owner="Administrator", module="LMS", title_field="source_access_id", fields=copy.deepcopy(target.FIELDS),
            permissions=[Row(role="System Manager", read=1)])
        self.db = self
        self.snapshot = None
        self.commits = self.rollbacks = self.bulk_calls = self.set_value_calls = self.cache_clears = 0
        self.corrupt_bulk = False
        self.queries = []

    def mapped(self):
        self.tables["User"]["user-private-key"] = Row(doctype="User", name="user-private-key",
            custom_avo_account=target.ACCOUNT, custom_avo_contact_id="201", enabled=1)
        self.tables["LMS Course"]["course-internal"] = Row(doctype="LMS Course", name="course-internal",
            custom_avo_account=target.ACCOUNT, custom_avo_id="301", published=0, disable_self_learning=1)
        return self

    def begin(self): self.snapshot = copy.deepcopy(self.tables)
    def commit(self): self.commits += 1
    def rollback(self):
        self.rollbacks += 1
        if self.snapshot is not None: self.tables = self.snapshot

    def exists(self, doctype, value):
        if isinstance(value, dict):
            rows = self.get_all(doctype, filters=value, fields=["name"])
            return rows[0]["name"] if rows else None
        return value if value in self.tables[doctype] else None

    def count(self, doctype): return len(self.tables[doctype])

    def clear_cache(self, **kwargs): self.cache_clears += 1

    def get_meta(self, doctype, **kwargs):
        if doctype == "DocPerm":
            return SimpleNamespace(fields=[Row(fieldname=key, fieldtype="Check")
                                           for key in {*target.PERMISSION_FLAGS, "read"}])
        data = self.tables["DocType"][doctype]
        fields = {row["fieldname"]: Row(row) for row in data["fields"]}
        return SimpleNamespace(custom=data["custom"], title_field=data["title_field"],
                               permissions=[Row(row) for row in data["permissions"]], get_field=fields.get)

    def set_value(self, doctype, name, values):
        self.set_value_calls += 1
        self.tables[doctype][name].update(copy.deepcopy(values))

    def get_all(self, doctype, filters=None, fields=None, limit_page_length=0, **kwargs):
        self.queries.append(doctype)
        result = []
        for row in self.tables[doctype].values():
            def match(key, condition):
                if isinstance(condition, (tuple, list)):
                    if condition[0] == "in": return row.get(key) in condition[1]
                    if condition[0] == "!=": return row.get(key) != condition[1]
                    raise AssertionError(condition)
                return row.get(key) == condition
            if all(match(key, condition) for key, condition in (filters or {}).items()):
                result.append(Row({key: row.get(key) for key in fields}) if fields else Row(row))
        return result[:limit_page_length] if limit_page_length else result

    def get_doc(self, data, name=None, **kwargs):
        if isinstance(data, dict): return FakeDoc(self, data)
        return FakeDoc(self, self.tables[data][name])

    def bulk_insert(self, doctype, *, fields, values):
        self.bulk_calls += 1
        for values_row in values:
            row = Row(zip(fields, values_row))
            if row["name"] in self.tables[doctype]: raise RuntimeError("duplicate")
            if self.corrupt_bulk: row["source_payload"] = "corrupt"
            self.tables[doctype][row["name"]] = row


class LedgerTest(unittest.TestCase):
    def setUp(self):
        self.tz = patch.object(target, "ZoneInfo", return_value=timezone(timedelta(hours=3)))
        self.tz.start(); self.addCleanup(self.tz.stop)
        self.app = FakeFrappe().mapped()

    def test_schema_is_custom_read_only_and_system_manager_read_only(self):
        self.assertTrue(target.ensure_schema(self.app)["ready"])
        data = self.app.tables["DocType"][target.DOCTYPE]
        self.assertTrue(all(row["read_only"] for row in data["fields"]))
        data["permissions"][0]["write"] = 1
        with self.assertRaisesRegex(target.Rejected, "registry_permissions_mismatch"):
            target.ensure_schema(self.app)

    def test_unique_field_supplies_index_when_frappe_clears_redundant_search_index(self):
        data = self.app.tables["DocType"][target.DOCTYPE]
        field = next(row for row in data["fields"] if row["fieldname"] == "source_access_id")
        field["search_index"] = 0
        self.assertTrue(target.ensure_schema(self.app)["ready"])
        field["unique"] = 0
        with self.assertRaisesRegex(target.Rejected, "registry_schema_mismatch"):
            target.ensure_schema(self.app)

    def test_schema_creation_explicitly_zeros_all_docperm_flags(self):
        del self.app.tables["DocType"][target.DOCTYPE]
        target.ensure_schema(self.app)
        permission = self.app.tables["DocType"][target.DOCTYPE]["permissions"][0]
        self.assertEqual(permission["read"], 1)
        self.assertEqual(permission["permlevel"], 0)
        self.assertTrue(all(permission[flag] == 0 for flag in target.PERMISSION_FLAGS))

    def test_only_empty_owned_initial_default_permissions_can_be_repaired(self):
        data = self.app.tables["DocType"][target.DOCTYPE]
        data["permissions"][0].update({flag: 1 for flag in target.INITIAL_DEFAULT_GRANTS})
        self.assertTrue(target.ensure_schema(self.app)["ready"])
        permission = self.app.tables["DocType"][target.DOCTYPE]["permissions"][0]
        self.assertTrue(all(permission.get(flag) == 0 for flag in target.PERMISSION_FLAGS))
        self.assertEqual(self.app.cache_clears, 1)
        self.assertEqual(self.app.commits, 1)

    def test_populated_or_foreign_or_changed_permission_settings_are_never_repaired(self):
        variants = ("populated", "other_owner", "other_module", "other_role", "unexpected_permission")
        for variant in variants:
            app = FakeFrappe().mapped()
            data = app.tables["DocType"][target.DOCTYPE]
            data["permissions"][0].update({flag: 1 for flag in target.INITIAL_DEFAULT_GRANTS})
            if variant == "populated": target.store_batch(app, [record()])
            if variant == "other_owner": data["owner"] = "other-user"
            if variant == "other_module": data["module"] = "Other"
            if variant == "other_role": data["permissions"][0]["role"] = "Other Role"
            if variant == "unexpected_permission": data["permissions"][0]["submit"] = 1
            before = copy.deepcopy(app.tables)
            with self.subTest(variant=variant), self.assertRaisesRegex(target.Rejected, "registry_permissions_mismatch"):
                target.ensure_schema(app)
            self.assertEqual(app.tables, before)
            self.assertEqual(app.cache_clears, 0)

    def test_schema_creation_is_explicit(self):
        del self.app.tables["DocType"][target.DOCTYPE]
        with self.assertRaisesRegex(target.Rejected, "registry_schema_not_initialized"):
            target.store_batch(self.app, [record()])
        target.ensure_schema(self.app)
        self.assertEqual(self.app.commits, 1)

    def test_stores_complete_immutable_snapshot_and_account_id_mappings(self):
        source = record()
        result = target.store_batch(self.app, [source])
        self.assertEqual(result["stored"], 1)
        saved = self.app.tables[target.DOCTYPE]["avo-mv-centr-access-101"]
        self.assertEqual(saved["source_payload"], target._canonical(source))
        self.assertEqual(saved["source_contact_id"], "201")
        self.assertEqual(saved["mapped_user"], "user-private-key")
        self.assertEqual(saved["mapped_course"], "course-internal")
        self.assertEqual(saved["captured_at"], "2026-10-13 11:16:00.864000")
        self.assertEqual(saved["sync_status"], "Stored")
        self.assertFalse(self.app.tables["LMS Enrollment"])
        self.assertFalse(self.app.tables["LMS Access Grant"])

    def test_idempotence_never_rewrites_activated_metadata(self):
        target.store_batch(self.app, [record()])
        saved = self.app.tables[target.DOCTYPE]["avo-mv-centr-access-101"]
        saved.update(sync_status="Applied", grant="existing-grant")
        result = target.store_batch(self.app, [record()])
        self.assertEqual(result["stored"], 0)
        self.assertEqual(result["already_stored"], 1)
        self.assertEqual(saved["grant"], "existing-grant")
        self.assertEqual(self.app.bulk_calls, 1)

    def test_source_null_unknown_flags_are_stored_without_fabrication(self):
        source = record()
        source["access"].update(frozen=None, ignore_course_end=None, day_access_shift=None, as_of=None)
        source["lessons"][0].update(assigned=None, accessible=None, hidden=None, day_access=None)
        target.store_batch(self.app, [source])
        saved = self.app.tables[target.DOCTYPE]["avo-mv-centr-access-101"]
        self.assertEqual(saved["source_payload"], target._canonical(source))

    def test_changed_snapshot_rejects_entire_batch_without_overwrite(self):
        target.store_batch(self.app, [record()])
        changed = record(); changed["access"]["frozen"] = True
        with self.assertRaisesRegex(target.Rejected, "source_snapshot_changed"):
            target.store_batch(self.app, [record("102"), changed])
        self.assertEqual(set(self.app.tables[target.DOCTYPE]), {"avo-mv-centr-access-101"})
        self.assertEqual(self.app.rollbacks, 1)

    def test_bulk_readback_mismatch_rolls_back(self):
        self.app.corrupt_bulk = True
        with self.assertRaisesRegex(target.Rejected, "ledger_readback_mismatch"):
            target.store_batch(self.app, [record()])
        self.assertFalse(self.app.tables[target.DOCTYPE])
        self.assertEqual(self.app.commits, 0)

    def test_noemail_contact_and_missing_course_are_pending(self):
        del self.app.tables["User"]["user-private-key"]
        self.app.tables["Contact"]["contact-internal"] = Row(name="contact-internal",
            custom_avo_account=target.ACCOUNT, custom_avo_contact_id="201", user=None)
        target.store_batch(self.app, [record()])
        saved = self.app.tables[target.DOCTYPE]["avo-mv-centr-access-101"]
        self.assertEqual(saved["sync_status"], "Pending Contact")
        self.assertEqual(saved["mapped_contact"], "contact-internal")
        self.assertIsNone(saved["mapped_user"])

        app = FakeFrappe().mapped(); app.tables["LMS Course"].clear()
        target.store_batch(app, [record()])
        self.assertEqual(app.tables[target.DOCTYPE]["avo-mv-centr-access-101"]["sync_status"], "Pending Course")

    def test_pending_mapping_refreshes_after_contact_import_without_rewriting_source(self):
        app = FakeFrappe()
        target.store_batch(app, [record()])
        original = app.tables[target.DOCTYPE]["avo-mv-centr-access-101"]["source_payload"]
        app.mapped()
        result = target.store_batch(app, [record()])
        row = app.tables[target.DOCTYPE]["avo-mv-centr-access-101"]
        self.assertEqual(result["refreshed"], 1)
        self.assertEqual((row["mapped_user"], row["mapped_course"], row["sync_status"]),
                         ("user-private-key", "course-internal", "Stored"))
        self.assertEqual(row["source_payload"], original)
        self.assertEqual(app.bulk_calls, 1)
        self.assertEqual(app.set_value_calls, 1)

    def test_applied_mapping_and_owned_native_references_never_refresh(self):
        for metadata in ({"sync_status": "Applied"}, {"grant": "owned-grant"}, {"enrollment": "owned-enrollment"}):
            app = FakeFrappe()
            target.store_batch(app, [record()])
            row = app.tables[target.DOCTYPE]["avo-mv-centr-access-101"]
            row.update(metadata)
            app.mapped()
            result = target.store_batch(app, [record()])
            self.assertEqual(result["refreshed"], 0)
            self.assertIsNone(row["mapped_user"])
            self.assertEqual(app.set_value_calls, 0)

    def test_different_account_is_never_mapping_fallback(self):
        self.app.tables["User"]["user-private-key"]["custom_avo_account"] = "iomp"
        target.store_batch(self.app, [record()])
        row = self.app.tables[target.DOCTYPE]["avo-mv-centr-access-101"]
        self.assertEqual(row["sync_status"], "Pending Contact")
        self.assertIsNone(row["mapped_user"])

    def test_ambiguous_target_mapping_is_preserved_for_review(self):
        self.app.tables["User"]["another"] = Row(self.app.tables["User"]["user-private-key"])
        self.app.tables["User"]["another"]["name"] = "another"
        target.store_batch(self.app, [record()])
        self.assertEqual(self.app.tables[target.DOCTYPE]["avo-mv-centr-access-101"]["sync_status"], "Needs Review")

    def test_batch_resolves_each_target_type_once_instead_of_per_record(self):
        records = [record(str(ident)) for ident in range(1, 101)]
        self.assertEqual(target.store_batch(self.app, records)["stored"], 100)
        self.assertEqual(self.app.queries.count("User"), 1)
        self.assertEqual(self.app.queries.count("Contact"), 1)
        self.assertEqual(self.app.queries.count("LMS Course"), 1)
        self.assertEqual(self.app.bulk_calls, 1)

    def test_source_shapes_scope_site_and_operator_fail_before_write(self):
        invalid = []
        for key, value in (("account", "iomp"), ("origin", "https://shop.iomp.ru"),
                           ("source_access_id", "100998"), ("source_access_id", "001"),
                           ("source_contact_id", True), ("schema_version", True)):
            source = record(); source[key] = value; invalid.append([source])
        source = record(); source["email"] = "private@example.test"; invalid.append([source])
        invalid.extend(([record(), record()], [], [record(str(i)) for i in range(1, 102)]))
        for batch in invalid:
            with self.subTest(batch_size=len(batch)), self.assertRaises(target.Rejected):
                target.store_batch(self.app, batch)
        for attr, value in (("site", "my-lk.iomp.ru"), ("user", "ordinary-user")):
            app = FakeFrappe().mapped()
            setattr(app.local if attr == "site" else app.session, attr, value)
            with self.assertRaises(target.Rejected): target.store_batch(app, [record()])
        self.assertEqual(self.app.bulk_calls, 0)

    def test_audit_returns_counts_only_and_does_not_create_schema(self):
        target.store_batch(self.app, [record()])
        self.assertEqual(target.audit(self.app), {"registry_exists": True, "ledger_count": 1, "statuses": {"Stored": 1}})
        del self.app.tables["DocType"][target.DOCTYPE]
        self.assertEqual(target.audit(self.app), {"registry_exists": False, "ledger_count": 0})


if __name__ == "__main__": unittest.main()

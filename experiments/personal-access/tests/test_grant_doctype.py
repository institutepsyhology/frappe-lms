"""Isolated schema and controller checks; these do not run a Frappe site."""

import importlib.util
import json
import sys
import types
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[3]
DOCTYPE = ROOT / "lms" / "lms" / "doctype"


class GrantDoctypeTests(unittest.TestCase):
    def setUp(self):
        self.courses = {"lesson-a": "course-a", "lesson-b": "course-b"}
        frappe = types.ModuleType("frappe")
        frappe.conf = {}
        frappe._ = lambda value: value
        frappe.throw = lambda value: (_ for _ in ()).throw(ValueError(value))
        frappe.db = types.SimpleNamespace(get_value=lambda doctype, name, field: self.courses.get(name))
        model = types.ModuleType("frappe.model")
        document = types.ModuleType("frappe.model.document")
        document.Document = type("Document", (), {})
        utils = types.ModuleType("frappe.utils")
        utils.get_datetime = lambda value: value if isinstance(value, datetime) else datetime.fromisoformat(value)
        utils.now_datetime = datetime.now
        self.modules = patch.dict(sys.modules, {"frappe": frappe, "frappe.model": model,
                                               "frappe.model.document": document, "frappe.utils": utils})
        self.modules.start()
        self.addCleanup(self.modules.stop)
        access_spec = importlib.util.spec_from_file_location("lms.lms.individual_access", ROOT / "lms/lms/individual_access.py")
        access = importlib.util.module_from_spec(access_spec)
        access_spec.loader.exec_module(access)
        self.access_patch = patch.dict(sys.modules, {"lms.lms.individual_access": access})
        self.access_patch.start()
        self.addCleanup(self.access_patch.stop)
        path = DOCTYPE / "lms_access_grant" / "lms_access_grant.py"
        spec = importlib.util.spec_from_file_location("test_access_grant_controller", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        self.cls = module.LMSAccessGrant

    def grant(self, **changes):
        doc = self.cls()
        values = {"course": "course-a", "status": "Active", "frozen_at": None, "starts_at": "2026-10-27 10:00:00",
                  "ends_at": "2026-10-28 10:00:00", "personal_end_type": "At",
                  "course_ends_at": None, "course_end_type": "Unknown",
                  "lessons": [types.SimpleNamespace(lesson="lesson-a", opening_type="Inherit", opens_at=None, delay_days=0)]}
        values.update(changes)
        for key, value in values.items():
            setattr(doc, key, value)
        return doc

    def test_only_selected_course_lessons_and_no_duplicates(self):
        self.grant().validate()
        for lessons in (["lesson-b"], ["missing"], ["lesson-a", "lesson-a"]):
            with self.subTest(lessons=lessons), self.assertRaises(ValueError):
                self.grant(lessons=[types.SimpleNamespace(lesson=x, opening_type="Inherit", opens_at=None, delay_days=0) for x in lessons]).validate()

    def test_end_before_start_is_rejected(self):
        for changes in ({"ends_at": "2026-10-27 10:00:00"},):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.grant(**changes).validate()

    def test_expired_general_course_end_can_be_ignored_for_an_individual(self):
        self.grant(course_ends_at="2026-10-26 10:00:00", course_end_type="At").validate()

    def test_unknown_unlimited_and_fixed_ends_are_distinct(self):
        self.grant(personal_end_type="Unknown", ends_at=None).validate()
        self.grant(personal_end_type="Unlimited", ends_at=None).validate()
        for changes in ({"personal_end_type": "At", "ends_at": None},
                        {"personal_end_type": "Unlimited", "ends_at": "2026-10-28 10:00:00"},
                        {"course_end_type": "Invalid"}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.grant(**changes).validate()

    def test_schema_is_admin_only_and_does_not_allow_deletion(self):
        schema = json.loads((DOCTYPE / "lms_access_grant" / "lms_access_grant.json").read_text(encoding="utf-8"))
        self.assertEqual([p["role"] for p in schema["permissions"]], ["System Manager"])
        self.assertTrue(all(not p.get("delete") for p in schema["permissions"]))
        self.assertEqual(next(f for f in schema["fields"] if f["fieldname"] == "status")["default"], "Draft")
        self.assertIn("does not control access", schema["description"])


if __name__ == "__main__":
    unittest.main()

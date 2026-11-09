"""Isolated tests for the AVO user importer authorization and safeguards."""
import importlib.util
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch


class ImportTest(unittest.TestCase):
    def setUp(self):
        self.docs = []
        self.frappe = types.ModuleType("frappe")
        f = self.frappe
        f.session = types.SimpleNamespace(user="Administrator")
        f.local = types.SimpleNamespace(site="my-lk.mv-centr.ru")
        f.flags = types.SimpleNamespace(in_import=False)
        f.PermissionError = PermissionError
        f.ValidationError = ValueError
        f.DuplicateEntryError = RuntimeError
        f.throw = lambda message, typ: (_ for _ in ()).throw(typ(message))
        f.parse_json = lambda data: data
        f.whitelist = lambda **kw: lambda fn: fn
        f.db = types.SimpleNamespace(exists=lambda *a: False)
        def get_doc(data):
            class FakeDoc:
                def __init__(self): self.data=data; self.flags=types.SimpleNamespace(); self.during=[]
                def run_method(self, method): self.during.append((method,f.flags.in_import))
                def insert(self, **kw): self.run_method('before_insert'); self.run_method('validate')
            doc = FakeDoc()
            self.docs.append(doc)
            return doc
        f.get_doc = get_doc
        utils = types.ModuleType("frappe.utils")
        utils.validate_email_address = lambda email, throw=False: "@" in email
        self.modules = patch.dict(sys.modules, {"frappe": f, "frappe.utils": utils})
        self.modules.start()
        self.addCleanup(self.modules.stop)
        spec = importlib.util.spec_from_file_location("avo_user_import", Path(__file__).with_name("avo_user_import.py"))
        self.module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.module)
        self.data = {"email": "test@example.invalid", "first_name": "Test", "new_password": "weak",
                     "custom_avo_contact_id": "17", "custom_avo_account": "mv-centr"}

    def test_import_preserves_password_without_welcome_email(self):
        self.assertEqual(self.module.import_user(self.data), {"created": True})
        self.assertTrue(self.docs[0].flags.ignore_password_policy)
        self.assertEqual(self.docs[0].data["new_password"], "weak")
        self.assertEqual(self.docs[0].data["send_welcome_email"], 0)
        self.assertEqual(self.docs[0].during, [('before_insert',True),('validate',False)])
        self.assertFalse(self.frappe.flags.in_import)

    def test_rejects_non_administrator(self):
        self.frappe.session.user = "student@example.invalid"
        with self.assertRaises(PermissionError):
            self.module.import_user(self.data)

    def test_rejects_duplicate_and_unexpected_fields(self):
        self.frappe.db.exists = lambda *args: True
        with self.assertRaises(RuntimeError):
            self.module.import_user(self.data)
        self.frappe.db.exists = lambda *args: False
        with self.assertRaises(ValueError):
            self.module.import_user({**self.data, "roles": ["System Manager"]})


if __name__ == "__main__":
    unittest.main()

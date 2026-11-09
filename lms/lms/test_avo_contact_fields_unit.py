"""Small isolated check for the source identity schema installer."""
import importlib.util
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch


class ContactFieldsTest(unittest.TestCase):
    def test_installs_only_private_identity_fields_on_user(self):
        captured = []
        name = "frappe.custom.doctype.custom_field.custom_field"
        mock = types.ModuleType(name)
        mock.create_custom_fields = lambda fields, update: captured.append((fields, update))
        modules = {}
        for part in ["frappe", "frappe.custom", "frappe.custom.doctype", "frappe.custom.doctype.custom_field"]:
            modules[part] = types.ModuleType(part)
        modules[name] = mock
        with patch.dict(sys.modules, modules):
            spec = importlib.util.spec_from_file_location("contact_fields", Path(__file__).with_name("avo_contact_fields.py"))
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            module.execute()
        fields, update = captured[0]
        self.assertTrue(update)
        self.assertEqual(set(fields), {"User"})
        self.assertEqual({x["fieldname"] for x in fields["User"]}, {
            "custom_avo_contact_id", "custom_avo_account", "custom_avo_telegram_id", "custom_avo_telegram_username",
            "custom_avo_vk_id", "custom_avo_vk_username"})
        self.assertTrue(all(x["permlevel"] == 1 for x in fields["User"]))


if __name__ == "__main__":
    unittest.main()

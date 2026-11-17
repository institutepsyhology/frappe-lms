"""Source-identity isolation without a running Frappe site."""
import copy
import importlib.util
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch


NATIVE_CONTACT_JOB = "frappe.core.doctype.user.user.create_contact"


class BindingTest(unittest.TestCase):
    def setUp(self):
        self.queries = []
        self.users = []
        self.frappe = types.ModuleType("frappe")
        self.frappe.local = types.SimpleNamespace(site="my-lk.mastervision.su")
        self.frappe.session = types.SimpleNamespace(user="Administrator")
        self.frappe.PermissionError = PermissionError
        self.frappe.whitelist = lambda **kwargs: lambda fn: fn
        self.frappe.get_all = self.get_all
        self.frappe.throw = self.throw
        spec = importlib.util.spec_from_file_location(
            "isolated_avo_contact_binding",
            Path(__file__).with_name("avo_contact_binding.py"),
        )
        self.module = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, {"frappe": self.frappe}):
            spec.loader.exec_module(self.module)

        class NativeContact(dict):
            def set_user(self):
                self["native_calls"] = self.get("native_calls", 0) + 1
                if not self.get("user") and self.get("email_id"):
                    self["user"] = "native-email-match"

            def __getattr__(self, key):
                return self.get(key)

            def __setattr__(self, key, value):
                self[key] = value

        self.Contact = type(
            "ExtendedContact", (self.module.AvoContactIdentityMixin, NativeContact), {}
        )

    def get_all(self, doctype, **kwargs):
        self.queries.append((doctype, kwargs))
        return list(self.users)

    @staticmethod
    def throw(message, exception=None):
        raise (exception or RuntimeError)(message)

    def contact(self, **changes):
        values = {
            "custom_avo_account": "mastervision",
            "custom_avo_contact_id": "101",
            "email_id": "shared@example.invalid",
            "user": None,
            "first_name": "Source name",
            "phone_nos": [],
        }
        values.update(changes)
        return self.Contact(values)

    def native_job(self, user):
        self.frappe.local.job = {
            "method": NATIVE_CONTACT_JOB,
            "kwargs": {"user": user},
        }

    def test_unmapped_contact_keeps_native_email_binding(self):
        contact = self.contact(custom_avo_account=None, custom_avo_contact_id="")
        contact.set_user()
        self.assertEqual(contact.user, "native-email-match")
        self.assertEqual(contact.native_calls, 1)
        self.assertEqual(self.queries, [])

    def test_unmapped_native_explicit_user_is_unchanged(self):
        contact = self.contact(
            custom_avo_account="", custom_avo_contact_id=None, user="native-explicit"
        )
        self.native_job({"name": "different-native"})
        contact.set_user()
        self.assertEqual(contact.user, "native-explicit")
        self.assertEqual(contact.native_calls, 1)

    def test_duplicate_email_contact_stays_separate_without_exact_user(self):
        contact = self.contact()
        contact.set_user()
        self.assertIsNone(contact.user)
        self.assertNotIn("native_calls", contact)
        self.assertEqual(
            self.queries,
            [("User", {
                "filters": {
                    "custom_avo_account": "mastervision",
                    "custom_avo_contact_id": "101",
                },
                "pluck": "name",
                "limit_page_length": 2,
            })],
        )

    def test_only_exact_source_user_can_bind_regardless_of_email(self):
        self.users = ["exact-source-user"]
        contact = self.contact(email_id="different@example.invalid")
        contact.set_user()
        self.assertEqual(contact.user, "exact-source-user")
        self.assertNotIn("native_calls", contact)

    def test_explicit_exact_user_is_preserved(self):
        self.users = ["exact-source-user"]
        contact = self.contact(user="exact-source-user")
        contact.set_user()
        self.assertEqual(contact.user, "exact-source-user")

    def test_explicit_foreign_user_fails_even_if_email_matches(self):
        self.users = ["exact-source-user"]
        contact = self.contact(user="foreign-user")
        with self.assertRaisesRegex(RuntimeError, "^AVO contact identity conflict\\.$"):
            contact.set_user()
        self.assertEqual(contact.user, "foreign-user")

    def test_explicit_user_without_exact_source_match_fails(self):
        with self.assertRaises(RuntimeError):
            self.contact(user="foreign-user").set_user()

    def test_partial_or_foreign_identity_fails_before_database_lookup(self):
        cases = [
            {"custom_avo_account": None},
            {"custom_avo_contact_id": None},
            {"custom_avo_account": "mv-centr"},
            {"custom_avo_account": "iomp"},
            {"custom_avo_account": " mastervision"},
            {"custom_avo_account": []},
        ]
        for changes in cases:
            with self.subTest(changes=changes), self.assertRaises(RuntimeError):
                self.contact(**changes).set_user()
        self.assertEqual(self.queries, [])

    def test_id_requires_canonical_positive_ascii_integer(self):
        for source_id in ("0", "001", "-1", "+1", "1.0", "1 ", "١", 1, True,
                          [], "9223372036854775808"):
            with self.subTest(source_id=source_id), self.assertRaises(RuntimeError):
                self.contact(custom_avo_contact_id=source_id).set_user()
        self.assertEqual(self.queries, [])

    def test_maximum_int64_source_id_is_accepted(self):
        contact = self.contact(custom_avo_contact_id="9223372036854775807")
        contact.set_user()
        self.assertIsNone(contact.user)

    def test_unknown_site_fails_for_source_identity_but_unmapped_is_native(self):
        self.frappe.local.site = "foreign.example.invalid"
        with self.assertRaises(RuntimeError):
            self.contact().set_user()
        ordinary = self.contact(custom_avo_contact_id=None, custom_avo_account=None)
        ordinary.set_user()
        self.assertEqual(ordinary.user, "native-email-match")

    def test_every_site_is_bound_to_its_own_account(self):
        for site, account in (
            ("my-lk.mv-centr.ru", "mv-centr"),
            ("my-lk.mastervision.su", "mastervision"),
            ("my-lk.iomp.ru", "iomp"),
            ("access-stage2.local", "mv-centr"),
        ):
            with self.subTest(site=site):
                self.frappe.local.site = site
                self.contact(custom_avo_account=account).set_user()
                self.assertEqual(self.queries[-1][1]["filters"]["custom_avo_account"], account)

    def test_ambiguous_exact_source_users_fail(self):
        self.users = ["exact-one", "exact-two"]
        with self.assertRaises(RuntimeError):
            self.contact().set_user()

    def test_reserved_or_malformed_database_user_fails(self):
        for name in (None, "", "Administrator", "Guest", {"name": "untrusted"}):
            with self.subTest(name=name), self.assertRaises(RuntimeError):
                self.users = [name]
                self.contact().set_user()

    def test_native_foreign_job_cannot_overwrite_source_contact_profile(self):
        persisted = copy.deepcopy(dict(self.contact()))
        contact = self.Contact(copy.deepcopy(persisted))
        # Native create_contact changes these before Contact.save(), without
        # setting contact.user in its existing-contact branch.
        contact.first_name = "Unrelated native user"
        contact.phone_nos.append({"phone": "000000"})
        self.native_job({"name": "foreign-native-user"})
        with self.assertRaises(RuntimeError):
            contact.set_user()
            persisted = copy.deepcopy(dict(contact))
        self.assertEqual(persisted["first_name"], "Source name")
        self.assertEqual(persisted["phone_nos"], [])
        self.assertIsNone(persisted["user"])

    def test_native_job_exact_user_is_allowed(self):
        self.users = ["exact-source-user"]
        self.native_job(types.SimpleNamespace(name="exact-source-user"))
        contact = self.contact()
        contact.set_user()
        self.assertEqual(contact.user, "exact-source-user")

    def test_native_foreign_job_is_rejected_when_exact_user_exists(self):
        self.users = ["exact-source-user"]
        self.native_job({"name": "foreign-source-user"})
        with self.assertRaises(RuntimeError):
            self.contact(user="exact-source-user").set_user()

    def test_malformed_native_job_context_fails_closed(self):
        self.users = ["exact-source-user"]
        for kwargs in ({}, {"user": None}, {"user": "exact-source-user"},
                       {"user": {}}, None):
            with self.subTest(kwargs=kwargs), self.assertRaises(RuntimeError):
                self.frappe.local.job = {"method": NATIVE_CONTACT_JOB, "kwargs": kwargs}
                self.contact().set_user()

    def test_other_background_job_does_not_claim_native_user_sync(self):
        self.frappe.local.job = {"method": "some.other.job", "kwargs": {}}
        contact = self.contact()
        contact.set_user()
        self.assertIsNone(contact.user)

    def test_fixed_error_does_not_expose_contact_data(self):
        contact = self.contact(user="private-name@example.invalid")
        with self.assertRaises(RuntimeError) as raised:
            contact.set_user()
        self.assertEqual(str(raised.exception), "AVO contact identity conflict.")
        self.assertNotIn(contact.email_id, str(raised.exception))

    def status(self, controller):
        base_document = types.ModuleType("frappe.model.base_document")
        base_document.get_controller = lambda doctype: controller
        with patch.dict(sys.modules, {"frappe.model.base_document": base_document}):
            return self.module.binding_status()

    def test_binding_status_reports_actual_controller_and_process_only(self):
        report = self.status(self.Contact)
        self.assertEqual(set(report), {"active", "pid", "site"})
        self.assertIs(report["active"], True)
        self.assertIsInstance(report["pid"], int)
        self.assertGreater(report["pid"], 0)
        self.assertEqual(report["site"], "my-lk.mastervision.su")
        self.assertEqual(self.queries, [])

    def test_binding_status_detects_stale_controller_without_mixin(self):
        report = self.status(dict)
        self.assertIs(report["active"], False)

    def test_binding_status_denies_non_administrator_even_if_staff(self):
        for name in ("Guest", "staff@example.invalid", None):
            with self.subTest(name=name), self.assertRaises(PermissionError):
                self.frappe.session.user = name
                # No controller import is needed or permitted before this check.
                self.module.binding_status()
        self.assertEqual(self.queries, [])


if __name__ == "__main__":
    unittest.main()

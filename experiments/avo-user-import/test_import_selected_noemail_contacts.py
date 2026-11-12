import copy
import unittest
from types import SimpleNamespace

import import_selected_noemail_contacts as importer


def record(ident="101", **changes):
    data = {"doctype": "Contact", "first_name": "Example", "middle_name": "",
            "last_name": "Person", "custom_avo_contact_id": ident,
            "custom_avo_account": "mv-centr", "custom_avo_telegram_id": "123456",
            "custom_avo_telegram_username": "example", "custom_avo_vk_id": "",
            "custom_avo_vk_username": "", "custom_avo_source_email": "",
            "custom_no_marketing_email": 1}
    data.update(changes)
    return data


def envelope(*records):
    return {"account": "mv-centr", "records": list(records)}


class FakeDocument(dict):
    def __init__(self, app, values):
        super().__init__(copy.deepcopy(values))
        self.app = app

    def insert(self, *, set_name):
        self.app.insert_names.append(set_name)
        if set_name in self.app.docs:
            raise RuntimeError("a private duplicate name that must not be printed")
        self["name"] = set_name
        self["phone_nos"] = self.get("phone_nos", [])
        if self["phone_nos"]:
            self["mobile_no"] = self["phone_nos"][0]["phone"]
        if self.app.corrupt_id == self["custom_avo_contact_id"]:
            self["custom_avo_telegram_username"] = "changed"
        self.app.docs[set_name] = copy.deepcopy(dict(self))
        return self


class FakeFrappe:
    def __init__(self):
        self.local = SimpleNamespace(site=importer.SITE)
        self.session = SimpleNamespace(user="Administrator")
        self.docs = {}
        self.users = []
        self.insert_names = []
        self.corrupt_id = None
        self.commits = 0
        self.rollbacks = 0
        self.snapshot = None
        self.db = self

    def begin(self):
        self.snapshot = copy.deepcopy(self.docs)

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1
        if self.snapshot is not None:
            self.docs = self.snapshot

    def get_all(self, doctype, *, filters, fields, limit_page_length):
        docs = self.users if doctype == "User" else list(self.docs.values())
        result = [{key: row.get(key) for key in fields} for row in docs
                  if str(row.get("custom_avo_contact_id")) == filters["custom_avo_contact_id"]]
        return result[:limit_page_length]

    def exists(self, doctype, name):
        return name in self.docs

    def get_doc(self, doctype_or_values, name=None):
        if isinstance(doctype_or_values, dict):
            return FakeDocument(self, doctype_or_values)
        return FakeDocument(self, self.docs[name])


class SelectedNoemailImportTest(unittest.TestCase):
    def setUp(self):
        self.app = FakeFrappe()

    def test_deterministic_name_preserves_profile_despite_native_name_collision(self):
        self.app.docs["Example Person"] = {"name": "Example Person", "first_name": "Example"}
        source = record()
        original = copy.deepcopy(source)
        result = importer.import_records(self.app, envelope(source))
        self.assertEqual(result, [{"contact_id": 101, "status": "created_verified"}])
        self.assertEqual(self.app.insert_names, ["avo-mv-centr-contact-101"])
        for key, value in source.items():
            self.assertEqual(self.app.docs["avo-mv-centr-contact-101"][key], value)
        self.assertEqual(source, original)
        self.assertEqual(self.app.commits, 1)

    def test_existing_exact_contact_is_idempotent_without_renaming(self):
        self.app.docs["legacy-name"] = {**record(), "name": "legacy-name"}
        self.assertEqual(importer.import_records(self.app, envelope(record())),
                         [{"contact_id": 101, "status": "already_present"}])
        self.assertEqual(self.app.insert_names, [])
        self.assertEqual(set(self.app.docs), {"legacy-name"})

    def test_wrong_account_site_or_operator_cannot_write(self):
        variants = [({"account": "iomp", "records": [record()]}, None, None),
                    (envelope(record(custom_avo_account="mastervision")), None, None),
                    (envelope(record()), "my-lk.iomp.ru", None),
                    (envelope(record()), None, "moderator@example.test")]
        for value, site, user in variants:
            with self.subTest(site=site, user=user, account=value["account"]):
                app = FakeFrappe()
                if site: app.local.site = site
                if user: app.session.user = user
                with self.assertRaises(importer.ImportRejected):
                    importer.import_records(app, value)
                self.assertEqual(app.insert_names, [])
                self.assertEqual(app.commits, 0)

    def test_invalid_payloads_fail_before_any_insert(self):
        invalid = [envelope(record(), record()), envelope(),
                   envelope(record("0")), envelope(record("001")),
                   envelope(record(True)), envelope(record(custom_no_marketing_email=True)),
                   envelope(record(email_id="example@example.test")),
                   envelope(record(custom_avo_source_email="example@example.test")),
                   envelope(record(phone_nos=[{"phone": "123", "is_primary_mobile_no": 0}])),
                   envelope(record(password="a secret")),
                   envelope(record(first_name=None)),
                   envelope(*[record(str(ident)) for ident in range(1, 12)])]
        for value in invalid:
            with self.subTest(value=value), self.assertRaises(importer.ImportRejected):
                importer.import_records(self.app, value)
        self.assertEqual(self.app.insert_names, [])
        self.assertEqual(self.app.commits, 0)

    def test_existing_user_with_same_source_id_is_not_changed_or_duplicated(self):
        self.app.users = [{"name": "example@example.test", "custom_avo_contact_id": "102",
                           "custom_avo_account": "mv-centr"}]
        with self.assertRaisesRegex(importer.ImportRejected, "source_id_conflict"):
            importer.import_records(self.app, envelope(record(), record("102")))
        self.assertEqual(self.app.insert_names, [])

    def test_existing_contact_mismatch_or_wrong_account_aborts_entire_batch(self):
        for changes in ({"first_name": "Other"}, {"custom_avo_account": "iomp"},
                        {"email_id": "example@example.test"},
                        {"phone_nos": [{"phone": "123", "is_primary_mobile_no": 1}]}):
            with self.subTest(changes=changes):
                self.app.docs["legacy"] = {**record("102"), **changes, "name": "legacy"}
                with self.assertRaises(importer.ImportRejected):
                    importer.import_records(self.app, envelope(record(), record("102")))
                self.assertEqual(self.app.insert_names, [])

    def test_two_cards_with_the_same_source_id_are_ambiguous(self):
        self.app.docs = {name: {**record(), "name": name} for name in ("one", "two")}
        with self.assertRaisesRegex(importer.ImportRejected, "source_id_conflict"):
            importer.import_records(self.app, envelope(record()))
        self.assertEqual(self.app.insert_names, [])

    def test_html_entity_normalization_applies_only_to_names(self):
        self.app.docs["legacy"] = {**record(first_name="A & B"), "name": "legacy"}
        source = record(first_name="A &amp; B")
        self.assertEqual(importer.import_records(self.app, envelope(source))[0]["status"],
                         "already_present")
        self.app.docs["legacy"]["custom_avo_telegram_username"] = "A & B"
        source["custom_avo_telegram_username"] = "A &amp; B"
        with self.assertRaisesRegex(importer.ImportRejected, "existing_contact_mismatch"):
            importer.import_records(self.app, envelope(source))

    def test_other_contact_owning_deterministic_name_aborts_before_write(self):
        self.app.docs["avo-mv-centr-contact-101"] = {**record("202"), "name": "avo-mv-centr-contact-101"}
        with self.assertRaisesRegex(importer.ImportRejected, "internal_name_conflict"):
            importer.import_records(self.app, envelope(record()))
        self.assertEqual(self.app.insert_names, [])

    def test_second_readback_failure_rolls_back_first_created_contact(self):
        self.app.corrupt_id = "102"
        with self.assertRaisesRegex(importer.ImportRejected, "readback_mismatch"):
            importer.import_records(self.app, envelope(record(), record("102")))
        self.assertEqual(self.app.docs, {})
        self.assertEqual(self.app.commits, 0)
        self.assertEqual(self.app.rollbacks, 1)

    def test_phone_and_raw_invalid_email_are_preserved_without_login_email(self):
        source = record(custom_avo_source_email="invalid-source-value",
                        phone_nos=[{"phone": "123456789", "is_primary_mobile_no": 1}])
        importer.import_records(self.app, envelope(source))
        saved = self.app.docs["avo-mv-centr-contact-101"]
        self.assertEqual(saved["phone_nos"], source["phone_nos"])
        self.assertEqual(saved["custom_avo_source_email"], source["custom_avo_source_email"])
        self.assertFalse(saved.get("email_id"))


if __name__ == "__main__":
    unittest.main()

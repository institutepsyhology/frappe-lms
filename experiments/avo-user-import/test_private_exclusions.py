import importlib.util
import io
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import import_mvcentr_users as source
import import_contacts_no_email as noemail


class PrivateExclusionsTest(unittest.TestCase):
    def load_rules(self, value):
        with patch.object(Path, "read_text", return_value=json.dumps(value)):
            return source.load_excluded_contacts(HERE / "private-rules.json")

    def test_missing_file_keeps_builtin_exclusion(self):
        with patch.object(Path, "read_text", side_effect=FileNotFoundError):
            self.assertEqual(source.load_excluded_contacts(), {10})

    def test_valid_private_ids_merge_with_builtin(self):
        self.assertEqual(self.load_rules({"account": "mv-centr", "excluded_ids": [101, 102]}),
                         {10, 101, 102})

    def test_builtin_can_be_present_once_in_private_list(self):
        self.assertEqual(self.load_rules({"account": "mv-centr", "excluded_ids": [10, 101]}),
                         {10, 101})

    def test_empty_private_list_preserves_builtin(self):
        self.assertEqual(self.load_rules({"account": "mv-centr", "excluded_ids": []}), {10})

    def test_default_file_is_account_specific_and_uses_bom_compatible_encoding(self):
        fake_root = HERE / "private-workspace"
        with patch.object(source, "ROOT", fake_root), \
             patch.object(Path, "read_text", autospec=True, return_value='{"account":"mv-centr","excluded_ids":[101]}') as read:
            self.assertEqual(source.load_excluded_contacts(), {10, 101})
        read.assert_called_once_with(
            fake_root / "exports/contacts-api-all-fields/mvcentr-excluded-contact-ids.json",
            encoding="utf-8-sig")

    def test_bom_prefixed_private_file_loads(self):
        contents = b'\xef\xbb\xbf{"account":"mv-centr","excluded_ids":[101]}'
        with patch.object(Path, "open", return_value=io.TextIOWrapper(io.BytesIO(contents), encoding="utf-8-sig")):
            self.assertEqual(source.load_excluded_contacts(HERE / "private-rules.json"), {10, 101})

    def test_fresh_import_initializes_shared_exclusions_from_private_file(self):
        spec = importlib.util.spec_from_file_location("isolated_importer", HERE / "import_mvcentr_users.py")
        fresh = importlib.util.module_from_spec(spec)
        with patch.object(Path, "read_text", return_value='{"account":"mv-centr","excluded_ids":[101]}'):
            spec.loader.exec_module(fresh)
        self.assertEqual(fresh.EXCLUDED_CONTACTS, {10, 101})

    def test_malformed_schema_and_other_accounts_fail_closed(self):
        invalid = [None, [], "mv-centr", {}, {"account": "mv-centr"},
                   {"account": "iomp", "excluded_ids": [101]},
                   {"account": "mastervision", "excluded_ids": [101]},
                   {"account": "mv-centr", "excluded_ids": None},
                   {"account": "mv-centr", "excluded_ids": "101"},
                   {"account": "mv-centr", "excluded_ids": {"101": True}},
                   {"account": "mv-centr", "excluded_ids": [], "unexpected": True}]
        for rules in invalid:
            with self.subTest(rules=rules), self.assertRaisesRegex(ValueError, "invalid_contact_exclusions"):
                self.load_rules(rules)

    def test_invalid_id_types_values_and_duplicates_fail_closed(self):
        for ids in ([True], [False], [0], [-1], ["101"], [101.0], [None], [[]], [{}], [101, 101]):
            with self.subTest(ids=ids), self.assertRaisesRegex(ValueError, "invalid_contact_exclusions"):
                self.load_rules({"account": "mv-centr", "excluded_ids": ids})

    def test_invalid_json_fails_closed(self):
        with patch.object(Path, "read_text", return_value="{"), self.assertRaises(ValueError):
            source.load_excluded_contacts(HERE / "private-rules.json")

    def test_unreadable_file_does_not_silently_skip_private_rules(self):
        with patch.object(Path, "read_text", side_effect=PermissionError), self.assertRaises(PermissionError):
            source.load_excluded_contacts(HERE / "private-rules.json")

    def test_result_is_independent_of_builtin_and_previous_load(self):
        first = self.load_rules({"account": "mv-centr", "excluded_ids": []})
        first.add(101)
        self.assertEqual(self.load_rules({"account": "mv-centr", "excluded_ids": []}), {10})

    def test_noemail_import_uses_shared_private_exclusions(self):
        record = {"contact": {"not_to_write": "0", "spam_clicked": "0", "name": "Test"}}
        with patch.object(source, "EXCLUDED_CONTACTS", {10, 101}), \
             patch.object(source, "load", return_value=iter([(101, record), (102, record)])), \
             patch.object(sys, "argv", ["importer"]), \
             patch("sys.stdout", new_callable=io.StringIO) as output:
            noemail.main()
        self.assertEqual(json.loads(output.getvalue())["eligible"], 1)

    def test_general_preflight_uses_shared_private_exclusions(self):
        records = [(101, {"contact": {"email": "first@example.test"}}),
                   (102, {"contact": {"email": "second@example.test"}})]
        with patch.object(source, "EXCLUDED_CONTACTS", {10, 101}), \
             patch.object(source, "load", side_effect=lambda: iter(records)), \
             patch.object(source, "payload", side_effect=lambda ident, record: {"email": record["contact"]["email"]}), \
             patch.object(sys, "argv", ["importer"]), \
             patch("sys.stdout", new_callable=io.StringIO) as output:
            source.main()
        counts = json.loads(output.getvalue())
        self.assertEqual(counts["eligible"], 1)
        self.assertEqual(counts["excluded_by_owner"], 1)


if __name__ == "__main__":
    unittest.main()

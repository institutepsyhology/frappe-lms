"""Synthetic-only tests for a private Master Vision ID selection."""
import codecs
import csv
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import unittest
from unittest.mock import patch
import uuid


SPEC = importlib.util.spec_from_file_location(
    "contact_selection", Path(__file__).with_name("contact_selection.py")
)
selection = importlib.util.module_from_spec(SPEC)
if SPEC.origin and Path(SPEC.origin).exists():
    SPEC.loader.exec_module(selection)


class SelectionTest(unittest.TestCase):
    def setUp(self):
        self.directory = Path(__file__).resolve().parents[2] / "exports" / (
            ".synthetic-contact-selection-" + uuid.uuid4().hex
        )
        self.directory.mkdir(parents=True)
        self.header = ["ID"] + ["Поле " + str(i) for i in range(1, 41)]

    def tearDown(self):
        # Only fixed synthetic files in this test's checked workspace folder.
        expected_parent = Path(__file__).resolve().parents[2] / "exports"
        self.assertEqual(self.directory.parent, expected_parent)
        for path in self.directory.iterdir():
            self.assertTrue(path.is_file())
            path.unlink()
        self.directory.rmdir()

    def row(self, source_id, **kwargs):
        result = [str(source_id)] + [""] * 40
        result[1] = kwargs.get("private", "Synthetic contact")
        return result

    def file(self, name, rows, *, encoding="utf-8-sig", header=None):
        text = io.StringIO(newline="")
        writer = csv.writer(text, delimiter=";", lineterminator="\r\n")
        writer.writerow(self.header if header is None else header)
        writer.writerows(rows)
        path = self.directory / name
        path.write_bytes(text.getvalue().encode(encoding))
        return path

    def assert_code(self, expected, paths, **kwargs):
        with self.assertRaises(selection.SelectionError) as raised:
            selection.build_selection(paths, **kwargs)
        self.assertEqual(raised.exception.code, expected)
        self.assertEqual(str(raised.exception), expected)

    def test_union_duplicates_and_pair_overlaps(self):
        paths = [
            self.file("one.csv", [self.row(9), self.row(2), self.row(2), self.row(5)]),
            self.file("two.csv", [self.row(5), self.row(9), self.row(12)]),
            self.file("three.csv", [self.row(9), self.row(20)]),
        ]
        result = selection.build_selection(paths)
        self.assertEqual(result["ids"], [2, 5, 9, 12, 20])
        manifest = result["manifest"]
        self.assertEqual(manifest["account"], "mastervision")
        self.assertEqual(manifest["format"], "mastervision-contact-selection-v1")
        self.assertEqual(manifest["rows"], 9)
        self.assertEqual(manifest["union_count"], 5)
        self.assertEqual(manifest["intrafile_duplicate_rows"], 1)
        self.assertEqual(manifest["interfile_repeated_memberships"], 3)
        self.assertEqual(manifest["interfile_duplicate_ids"], 2)
        self.assertEqual(manifest["total_duplicate_rows"], 4)
        self.assertEqual(manifest["pair_overlaps"], [
            {"files": [0, 1], "count": 2},
            {"files": [0, 2], "count": 1},
            {"files": [1, 2], "count": 1},
        ])
        self.assertEqual(manifest["all_files_overlap"], 1)
        self.assertEqual(manifest["fingerprint"], hashlib.sha256(b"2\n5\n9\n12\n20\n").hexdigest())

    def test_file_hash_is_exact_original_bytes_and_sources_unchanged(self):
        path = self.file("source.csv", [self.row(4)])
        before = path.read_bytes(), path.stat().st_mtime_ns
        result = selection.build_selection([path])
        report = result["manifest"]["files"][0]
        self.assertEqual(report["sha256"], hashlib.sha256(before[0]).hexdigest())
        self.assertEqual(report["bytes"], len(before[0]))
        self.assertEqual(before, (path.read_bytes(), path.stat().st_mtime_ns))
        self.assertEqual(report["header"]["columns"], 41)
        self.assertEqual(report["header"]["id_column"], "ID")

    def test_personal_fields_are_neither_returned_nor_copied_into_manifest(self):
        private = "private@example.invalid;private-password\nprivate-name"
        path = self.file("synthetic.csv", [self.row(42, private=private)])
        result = selection.build_selection([path])
        encoded = json.dumps(result, ensure_ascii=True)
        self.assertEqual(set(result), {"ids", "manifest"})
        self.assertNotIn("private@example", encoded)
        self.assertNotIn("private-password", encoded)
        self.assertNotIn("private-name", encoded)
        self.assertNotIn(str(self.directory), encoded)

    def test_quoted_semicolons_and_multiline_fields_remain_one_record(self):
        path = self.file("quoted.csv", [self.row(2, private='Text; "quoted"\r\nnext line'), self.row(10)])
        result = selection.build_selection([path])
        self.assertEqual(result["ids"], [2, 10])
        self.assertEqual(result["manifest"]["rows"], 2)

    def test_utf8_with_and_without_bom(self):
        for encoding in ("utf-8", "utf-8-sig"):
            with self.subTest(encoding=encoding):
                path = self.file(encoding + ".csv", [self.row(1)], encoding=encoding)
                self.assertEqual(selection.build_selection([path])["ids"], [1])

    def test_utf16_both_endian_boms(self):
        path = self.file("utf16.csv", [self.row(77)], encoding="utf-16")
        original = path.read_bytes().decode("utf-16")
        for label, bom in (("utf-16-le", codecs.BOM_UTF16_LE), ("utf-16-be", codecs.BOM_UTF16_BE)):
            with self.subTest(label=label):
                path.write_bytes(bom + original.encode(label))
                self.assertEqual(selection.build_selection([path])["ids"], [77])

    def test_cp1251_requires_explicit_selection(self):
        path = self.file("legacy.csv", [self.row(3)], encoding="cp1251")
        self.assert_code("encoding_invalid", [path])
        self.assertEqual(selection.build_selection([path], encoding="cp1251")["ids"], [3])

    def test_bom_and_explicit_encoding_conflict_fails(self):
        path = self.file("bom.csv", [self.row(3)])
        self.assert_code("encoding_conflict", [path], encoding="cp1251")

    def test_unknown_encoding_is_not_guessed(self):
        path = self.file("source.csv", [self.row(1)])
        self.assert_code("encoding_unsupported", [path], encoding="latin1")
        path.write_bytes(codecs.BOM_UTF32_LE + "ID".encode("utf-32-le"))
        self.assert_code("encoding_unsupported", [path])

    def test_first_header_is_exact_ascii_id(self):
        for first in ("id", " ID", "ID ", "Email", "ИД"):
            with self.subTest(first=first):
                path = self.file("bad-header.csv", [self.row(1)], header=[first] + self.header[1:])
                self.assert_code("header_invalid", [path])

    def test_header_width_is_the_known_41_columns(self):
        path = self.file("bad-header.csv", [self.row(1)], header=self.header[:-1])
        self.assert_code("header_invalid", [path])

    def test_header_mismatch_between_files_fails(self):
        one = self.file("one.csv", [self.row(1)])
        header = list(self.header); header[-1] = "Different field"
        two = self.file("two.csv", [self.row(2)], header=header)
        self.assert_code("header_mismatch", [one, two])

    def test_short_or_long_row_fails_without_guessing_id(self):
        for row in (["1"], self.row(1) + ["extra"]):
            with self.subTest(width=len(row)):
                path = self.file("width.csv", [row])
                self.assert_code("row_width", [path])

    def test_blank_id_is_separate_from_malformed_id(self):
        path = self.file("blank.csv", [self.row("")])
        self.assert_code("id_blank", [path])
        path = self.file("empty-record.csv", [[]])
        self.assert_code("id_blank", [path])

    def test_bad_id_is_rejected_not_coerced_or_taken_from_email(self):
        for source_id in ("0", "001", "-1", "+1", "1.0", "1e2", "1 ", " 1", "١", "²", "9223372036854775808", "private@example.invalid"):
            with self.subTest(source_id=source_id):
                path = self.file("bad.csv", [self.row(source_id, private="123@example.invalid")])
                self.assert_code("id_invalid", [path])

    def test_int64_maximum_is_accepted_and_sort_is_numeric(self):
        path = self.file("max.csv", [self.row(9223372036854775807), self.row(100), self.row(2)])
        self.assertEqual(selection.build_selection([path])["ids"], [2, 100, 9223372036854775807])

    def test_empty_file_or_header_only_cannot_authorize_empty_selection(self):
        empty = self.directory / "empty.csv"; empty.write_bytes(b"")
        self.assert_code("header_invalid", [empty])
        header_only = self.file("header.csv", [])
        self.assert_code("selection_empty", [header_only])

    def test_csv_syntax_error_has_fixed_error_without_private_cell_data(self):
        path = self.file("syntax.csv", [])
        with path.open("a", encoding="utf-8") as stream:
            stream.write('1;"private@example.invalid')
        self.assert_code("csv_invalid", [path])

    def test_missing_file_and_non_file_fail_with_fixed_codes(self):
        self.assert_code("source_unreadable", [self.directory / "not-present.csv"])
        self.assert_code("source_not_regular", [self.directory])

    def test_no_paths_or_single_path_string_is_invalid(self):
        self.assert_code("paths_invalid", [])
        self.assert_code("paths_invalid", "not-a-list.csv")

    def test_source_mutation_during_read_invalidates_complete_result(self):
        path = self.file("changing.csv", [self.row(1)])
        old_readinto = selection._HashingReader.readinto
        changed = False

        def mutate(reader, buffer):
            nonlocal changed
            result = old_readinto(reader, buffer)
            if not changed:
                changed = True
                with path.open("ab") as output:
                    text = io.StringIO(newline="")
                    csv.writer(text, delimiter=";").writerow(self.row(2))
                    output.write(text.getvalue().encode())
            return result

        with patch.object(selection._HashingReader, "readinto", mutate):
            self.assert_code("source_changed", [path])

    def test_fingerprint_is_independent_of_file_and_row_order(self):
        first = self.file("one.csv", [self.row(10), self.row(2)])
        second = self.file("two.csv", [self.row(30), self.row(10)])
        forward = selection.build_selection([first, second])
        reverse = selection.build_selection([second, first])
        self.assertEqual(forward["ids"], reverse["ids"])
        self.assertEqual(forward["manifest"]["fingerprint"], reverse["manifest"]["fingerprint"])

    def test_prior_source_change_while_reading_later_source_invalidates_union(self):
        first = self.file("first.csv", [self.row(1)])
        second = self.file("second.csv", [self.row(2)])
        original = selection._read_file

        def change_prior(path, encoding):
            result = original(path, encoding)
            if path == second:
                with first.open("ab") as stream:
                    stream.write(b"\r\n")
            return result

        with patch.object(selection, "_read_file", change_prior):
            self.assert_code("source_changed", [first, second])

    def test_field_limit_is_restored_after_success_and_failure(self):
        old_limit = csv.field_size_limit()
        path = self.file("field.csv", [self.row(1)])
        selection.build_selection([path])
        self.assertEqual(csv.field_size_limit(), old_limit)
        path = self.file("bad-id.csv", [self.row("bad")])
        self.assert_code("id_invalid", [path])
        self.assertEqual(csv.field_size_limit(), old_limit)


if __name__ == "__main__":
    unittest.main()

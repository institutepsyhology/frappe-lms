"""Synthetic account-isolation and uncertain-write tests; no credentials/network."""
import copy
import json
import unittest
from unittest.mock import patch

import importer as mod


def payload(lesson, course=618):
    return {"account": "mastervision", "source_origin": "https://shop.mastervision.su",
            "course_id": course, "lesson_id": lesson, "course_title": "Synthetic course",
            "lesson_title": "Synthetic lesson", "format": "ape",
            "ape": {"name": "page", "children": [{"name": "text", "fields": {"text": "PRIVATE SOURCE"}}]}}


class Client:
    site, account = "my-lk.mastervision.su", "mastervision"

    def __init__(self, existing=()):
        self.existing = [str(value) for value in existing]
        self.present = bool(existing)
        self.calls, self.writes, self.previews = [], [], []
        self.not_ready, self.foreign_preview, self.bad_route = set(), False, False
        self.wrong_account, self.write_fails, self.readback_fails = False, False, False
        self.inject_after_preview = None
        self.course_id = "618"

    def course(self):
        return {"name": "target-course", "custom_avo_account": "mastervision", "custom_avo_id": self.course_id,
                "custom_lms_id": self.course_id, "published": 0, "chapters": [{"chapter": "target-chapter"}]}

    def lesson(self, ident):
        return {"name": "lesson-" + ident, "custom_avo_account": "mv-centr" if self.wrong_account else "mastervision",
                "custom_avo_id": ident, "custom_lms_id": "999" if self.bad_route else ident,
                "course": "target-course", "chapter": "target-chapter", "is_draft": 1, "include_in_preview": 0}

    def call(self, tool, args):
        self.calls.append((tool, copy.deepcopy(args)))
        if tool == "list_documents":
            if args["doctype"] == "LMS Course":
                return {"documents": [self.course()] if self.present else [], "has_next_page": False}
            names = args["filters"][0][2]
            return {"documents": [self.lesson(i) for i in reversed(self.existing) if "lesson-" + i in names], "has_next_page": False}
        if tool == "get_document":
            if args["doctype"] == "LMS Course":
                return self.course()
            return {"name": "target-chapter", "course": "target-course", "is_scorm_package": 0,
                    "lessons": [{"idx": idx, "lesson": "lesson-" + value} for idx, value in enumerate(self.existing, 1)]}
        if tool != "call_method" or args["method"] != "lms.lms.avo_import.import_lesson":
            raise AssertionError("unexpected tool")
        request = args["args"]
        ident = str(request["payload"]["lesson_id"])
        if request["dry_run"]:
            self.previews.append(ident)
            result = {"account": "mv-centr" if self.foreign_preview else "mastervision", "course_id": self.course_id,
                      "lesson_id": ident, "dry_run": True, "ready": ident not in self.not_ready,
                      "issues": ["unknown_block"] if ident in self.not_ready else [], "warnings": [],
                      "action": "already_imported" if ident in self.existing else "create_course_and_lesson"}
            if self.readback_fails and self.writes:
                result["action"] = "create_lesson"
            if self.inject_after_preview and len(self.previews) == self.inject_after_preview[0]:
                self.existing.append(self.inject_after_preview[1])
                self.present = True
            return {"result": result}
        self.writes.append(ident)
        self.present = True
        self.existing.append(ident)
        if self.write_fails:
            raise RuntimeError("PRIVATE response after possible commit")
        return {"result": {"action": "created", "account": "mastervision", "course_id": self.course_id,
                           "lesson_id": ident, "dry_run": False}}


class ImportTests(unittest.TestCase):
    def test_wrong_client_site_rejected(self):
        client = Client()
        client.site = "my-lk.mv-centr.ru"
        with self.assertRaisesRegex(mod.Stop, "wrong_frappe_site"):
            mod.Importer(client)
        self.assertEqual(client.calls, [])

    def test_mixed_source_account_rejected_before_any_request(self):
        client = Client()
        source = [payload(1), payload(2)]
        source[1]["account"] = "mv-centr"
        with self.assertRaisesRegex(mod.Stop, "source_account_mismatch"):
            mod.Importer(client).import_course(source, apply=True)
        self.assertEqual(client.calls, [])

    def test_wrong_origin_rejected_before_any_request(self):
        client = Client()
        source = payload(1)
        source["source_origin"] = "https://shop.mv-centr.ru"
        with self.assertRaisesRegex(mod.Stop, "source_account_mismatch"):
            mod.Importer(client).import_course([source], apply=True)
        self.assertEqual(client.calls, [])

    def test_duplicate_or_mixed_course_ids_never_write(self):
        for values in ([payload(1), payload(1)], [payload(1), payload(2, 619)]):
            with self.subTest(values=len(values)):
                client = Client()
                with self.assertRaises(mod.Review):
                    mod.Importer(client).import_course(values, apply=True)
                self.assertEqual(client.calls, [])

    def test_noncanonical_ids_and_nonfinite_source_are_rejected_before_requests(self):
        for value in (True, 0, -1, 1.0, "01", "1.0", 2147483648):
            client = Client()
            with self.subTest(value=value), self.assertRaises(mod.Review):
                mod.Importer(client).import_course([payload(value)], apply=True)
            self.assertEqual(client.calls, [])
        client = Client()
        source = payload(1)
        source["ape"]["unexpected"] = float("nan")
        with self.assertRaises(mod.Review):
            mod.Importer(client).import_course([source], apply=True)
        self.assertEqual(client.calls, [])

    def test_dry_run_preflights_every_lesson_without_writes_or_source_in_result(self):
        client = Client()
        result = mod.Importer(client).import_course([payload(1), payload(2)])
        self.assertEqual(client.previews, ["1", "2"])
        self.assertEqual(client.writes, [])
        self.assertEqual(result["status"], "ready")
        self.assertNotIn("PRIVATE", json.dumps(result))

    def test_not_ready_lesson_reports_problem_and_no_partial_course_is_written(self):
        client = Client()
        client.not_ready.add("2")
        with self.assertRaisesRegex(mod.Review, "course_needs_review") as raised:
            mod.Importer(client).import_course([payload(1), payload(2), payload(3)], apply=True)
        self.assertEqual(client.previews, ["1", "2", "3"])
        self.assertEqual(client.writes, [])
        self.assertEqual(raised.exception.problems, [{"lesson_id": "2", "codes": ["unknown_block"]}])

    def test_preserves_verified_prefix_and_reads_back_each_missing_lesson(self):
        client = Client([1])
        result = mod.Importer(client).import_course([payload(1), payload(2), payload(3)], apply=True)
        self.assertEqual(client.previews, ["1", "2", "3", "2", "3"])
        self.assertEqual(client.writes, ["2", "3"])
        self.assertEqual(result["existing_lesson_ids"], ["1"])
        self.assertEqual(result["created_lesson_ids"], ["2", "3"])
        self.assertEqual(result["status"], "created")

    def test_full_existing_course_still_checks_snapshots_without_overwriting(self):
        client = Client([1, 2])
        result = mod.Importer(client).import_course([payload(1), payload(2)], apply=True)
        self.assertEqual(client.previews, ["1", "2"])
        self.assertEqual(client.writes, [])
        self.assertEqual(result["status"], "already_present")

    def test_large_outline_uses_complete_bounded_batches(self):
        client = Client(range(1, 202))
        mod.Importer(client).import_course([payload(i) for i in range(1, 202)])
        batches = [args["limit"] for tool, args in client.calls
                   if tool == "list_documents" and args["doctype"] == "Course Lesson"]
        self.assertEqual(batches, [100, 100, 1])

    def test_published_target_is_never_changed(self):
        client = Client([1])
        course = client.course()
        course["published"] = 1
        client.course = lambda: course
        with self.assertRaisesRegex(mod.Review, "course_not_draft"):
            mod.Importer(client).import_course([payload(1)], apply=True)
        self.assertEqual(client.writes, [])

    def test_existing_nonprefix_order_is_not_repaired_or_overwritten(self):
        client = Client([2])
        with self.assertRaisesRegex(mod.Review, "course_order_conflict"):
            mod.Importer(client).import_course([payload(1), payload(2)], apply=True)
        self.assertEqual(client.writes, [])

    def test_foreign_target_identity_and_wrong_numeric_route_are_rejected(self):
        for attribute in ("wrong_account", "bad_route"):
            client = Client([1])
            setattr(client, attribute, True)
            with self.subTest(attribute=attribute), self.assertRaises(mod.Review):
                mod.Importer(client).import_course([payload(1)], apply=True)
            self.assertEqual(client.writes, [])

    def test_foreign_preview_response_stops_without_write(self):
        client = Client()
        client.foreign_preview = True
        with self.assertRaisesRegex(mod.Stop, "preview_identity_invalid"):
            mod.Importer(client).import_course([payload(1)], apply=True)
        self.assertEqual(client.writes, [])

    def test_concurrent_outline_change_stops_before_first_write(self):
        client = Client()
        client.inject_after_preview = (2, "99")
        with self.assertRaisesRegex(mod.Stop, "course_changed_during_import"):
            mod.Importer(client).import_course([payload(1), payload(2)], apply=True)
        self.assertEqual(client.writes, [])

    def test_changed_source_flags_after_preflight_are_a_stop(self):
        client = Client([1])
        original = client.call
        def change_flags(tool, args):
            result = original(tool, args)
            if tool == "call_method" and args["args"]["dry_run"] and args["args"]["payload"]["lesson_id"] == 2:
                client.wrong_account = True
            return result
        client.call = change_flags
        with self.assertRaisesRegex(mod.Stop, "course_changed_during_import"):
            mod.Importer(client).import_course([payload(1), payload(2)], apply=True)
        self.assertEqual(client.writes, [])

    def test_uncertain_commit_stops_and_does_not_continue_to_next_lesson(self):
        client = Client()
        client.write_fails = True
        with self.assertRaisesRegex(mod.Stop, "write_result_uncertain") as raised:
            mod.Importer(client).import_course([payload(1), payload(2)], apply=True)
        self.assertEqual(client.writes, ["1"])
        self.assertNotIn("PRIVATE", str(raised.exception))

    def test_readback_mismatch_stops_before_next_write(self):
        client = Client()
        client.readback_fails = True
        with self.assertRaisesRegex(mod.Stop, "write_result_uncertain"):
            mod.Importer(client).import_course([payload(1), payload(2)], apply=True)
        self.assertEqual(client.writes, ["1"])

    def test_mvc_numeric_exclusions_do_not_apply_to_mastervision(self):
        client = Client()
        client.course_id = "50"
        mod.Importer(client).import_course([payload(17, 50), payload(19, 50)], apply=True)
        self.assertEqual(client.writes, ["17", "19"])

    def test_image_preparer_receives_copy_and_private_images_are_not_returned(self):
        client = Client()
        source = payload(1)
        def prepare(value):
            value["account"] = "mv-centr"
            return {"image": "PRIVATE BASE64"}
        result = mod.Importer(client).import_course([source], images_for_lesson=prepare)
        self.assertEqual(source["account"], "mastervision")
        calls = [args for name, args in client.calls if name == "call_method"]
        self.assertEqual(calls[0]["args"]["payload"]["account"], "mastervision")
        self.assertEqual(calls[0]["args"]["images"], {"image": "PRIVATE BASE64"})
        self.assertNotIn("PRIVATE", json.dumps(result))

    def test_image_preparer_failure_is_a_fixed_redacted_review(self):
        client = Client()
        def prepare(value):
            raise ValueError("PRIVATE source URL")
        with self.assertRaises(mod.Review) as raised:
            mod.Importer(client).import_course([payload(1)], apply=True, images_for_lesson=prepare)
        self.assertEqual(raised.exception.problems, [{"lesson_id": "1", "codes": ["image_requires_preparation"]}])
        self.assertEqual(client.writes, [])

    def test_image_bytes_must_be_encoded_by_preparer(self):
        client = Client()
        with self.assertRaises(mod.Review) as raised:
            mod.Importer(client).import_course([payload(1)], apply=True, images_for_lesson=lambda p: {"image": b"unencoded"})
        self.assertEqual(raised.exception.problems, [{"lesson_id": "1", "codes": ["image_requires_preparation"]}])
        self.assertEqual(client.writes, [])

    def test_missing_image_preparation_is_explicit_review(self):
        client = Client()
        original = client.call
        def reject_preview(tool, args):
            if tool == "call_method":
                raise mod.Review("mcp_rejected_request")
            return original(tool, args)
        client.call = reject_preview
        source = payload(1)
        source["ape"]["children"] = [{"name": "image", "id": "image", "fields": {"imageSrc": "PRIVATE SOURCE"}}]
        with self.assertRaises(mod.Review) as raised:
            mod.Importer(client).import_course([source], apply=True)
        self.assertEqual(raised.exception.problems, [{"lesson_id": "1", "codes": ["image_requires_preparation"]}])
        self.assertEqual(client.writes, [])


class Response:
    def __init__(self, body):
        self.body = json.dumps(body).encode()
    def __enter__(self):
        return self
    def __exit__(self, *args):
        pass
    def read(self, *args):
        return self.body


class MCPTests(unittest.TestCase):
    def test_wrong_server_identity_is_rejected_without_tools_calls(self):
        class Opener:
            def open(self, req, **kwargs):
                value = json.loads(req.data)
                return Response({"id": value["id"], "result": {"serverInfo": {"name": "my_lk_mv_centr_ru"}}})
        with patch.object(mod, "authentication", return_value=({"Cookie": "sid=PRIVATE"}, mod.urllib.request.HTTPRedirectHandler)), patch.object(mod.urllib.request, "build_opener", return_value=Opener()):
            with self.assertRaisesRegex(mod.Stop, "wrong_frappe_site"):
                mod.MCPClient()

    def test_transport_is_fixed_to_mastervision_and_does_not_expose_remote_errors(self):
        urls = []
        class Opener:
            def open(self, req, **kwargs):
                urls.append(req.full_url)
                value = json.loads(req.data)
                result = {"serverInfo": {"name": "my_lk_mastervision_su"}} if value["method"] == "initialize" else {"isError": True, "content": [{"text": "PRIVATE remote source"}]}
                return Response({"id": value["id"], "result": result})
        with patch.object(mod, "authentication", return_value=({"Cookie": "sid=PRIVATE"}, mod.urllib.request.HTTPRedirectHandler)), patch.object(mod.urllib.request, "build_opener", return_value=Opener()):
            client = mod.MCPClient()
            with self.assertRaisesRegex(mod.Review, "mcp_rejected_request") as raised:
                client.call("list_documents", {})
            self.assertNotIn("PRIVATE", str(raised.exception))
        self.assertEqual(set(urls), {"https://my-lk.mastervision.su/api/v2/mcp"})


if __name__ == "__main__":
    unittest.main()

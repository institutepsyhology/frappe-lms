"""Synthetic empty-course proof and guarded single-parent creation tests."""
import copy
import html
import json
import unittest

from importer import Review, Stop
import source
import course_metadata as mod


def snapshot(title="Synthetic empty course"):
    page = '<form action="/shop/training/admin/update?id=4&amp;lg=ru">' \
           '<input name="TrainingForm[id_training]" value="4">' \
           '<input name="TrainingForm[training]" value="' + html.escape(title, quote=True) + '"></form>' \
           '<script>AWO.training.LessonsEditor("#editor", {"trainingLessonsTree": []});</script>'
    return {"account": "mastervision", "origin": "https://shop.mastervision.su", "verified": True,
            "error": None, "html": page, "parsed": source.parse_course(page, 4)}


class Client:
    account, site = "mastervision", "my-lk.mastervision.su"

    def __init__(self):
        self.doc, self.foreign_number = None, None
        self.reads, self.writes = [], []
        self.links = {}
        self.write_fails, self.corrupt_created = False, False
        self.source_queries, self.concurrent_create = 0, False

    def document(self, title="Synthetic empty course"):
        return {"name": "synthetic-empty-course", "custom_avo_account": "mastervision", "custom_avo_id": "4",
                "custom_lms_id": "4", "title": title, "short_introduction": title, "description": title,
                "published": 0, "disable_self_learning": 1, "chapters": [], "instructors": [{"instructor": "Administrator"}]}

    def call(self, tool, args):
        self.reads.append((tool, copy.deepcopy(args)))
        if tool == "get_document":
            return copy.deepcopy(self.doc)
        if tool != "list_documents":
            raise AssertionError("unexpected read tool")
        if args["doctype"] == "LMS Course":
            numeric = args["filters"][0][0] == "custom_lms_id"
            if not numeric:
                self.source_queries += 1
                if self.concurrent_create and self.source_queries == 2:
                    self.doc = self.document()
            rows = [self.foreign_number] if numeric and self.foreign_number else [self.doc] if self.doc else []
        else:
            rows = [{"name": "synthetic-linked-record"}] if self.links.get(args["doctype"]) else []
        return {"documents": copy.deepcopy(rows), "has_next_page": False}

    def rpc(self, method, args):
        self.writes.append((method, copy.deepcopy(args)))
        if method != "tools/call" or args["name"] != "create_document" or args["arguments"]["doctype"] != "LMS Course":
            raise AssertionError("unexpected mutation")
        self.doc = {**args["arguments"]["data"], "name": "synthetic-empty-course", "chapters": []}
        if self.corrupt_created:
            self.doc["published"] = 1
        if self.write_fails:
            raise RuntimeError("PRIVATE remote response after possible commit")
        return {"structuredContent": copy.deepcopy(self.doc), "isError": False}


class EmptyCourseTests(unittest.TestCase):
    def test_dry_run_reads_only_and_returns_no_source_content(self):
        client, record = Client(), snapshot()
        result = mod.ensure_empty_course(client, record)
        self.assertEqual(result["status"], "ready")
        self.assertEqual(result["course_id"], "4")
        self.assertEqual(client.writes, [])
        self.assertNotIn("Synthetic empty", json.dumps(result))
        self.assertNotIn("html", result)

    def test_create_exactly_one_draft_parent_with_genuine_numeric_identity(self):
        client, record = Client(), snapshot()
        original = copy.deepcopy(record)
        result = mod.ensure_empty_course(client, record, apply=True)
        self.assertEqual(record, original)
        self.assertEqual(result["status"], "created")
        self.assertEqual(len(client.writes), 1)
        data = client.writes[0][1]["arguments"]["data"]
        self.assertEqual((data["custom_avo_account"], data["custom_avo_id"], data["custom_lms_id"]), ("mastervision", "4", "4"))
        self.assertEqual((data["published"], data["disable_self_learning"]), (0, 1))
        self.assertEqual(data["instructors"], [{"instructor": "Administrator"}])
        self.assertFalse(any(key in data for key in ("chapters", "lessons", "enrollments", "grants")))
        checked = {args["doctype"] for tool, args in client.reads if tool == "list_documents"}
        self.assertTrue({"Course Lesson", "LMS Enrollment", "LMS Access Grant"} <= checked)

    def test_existing_matching_empty_draft_is_verified_and_not_overwritten(self):
        client = Client()
        client.doc = client.document()
        self.assertEqual(mod.ensure_empty_course(client, snapshot(), apply=True)["status"], "already_present")
        self.assertEqual(client.writes, [])

    def test_manual_title_changes_are_not_overwritten(self):
        client = Client()
        client.doc = client.document("Manual title")
        with self.assertRaises(Review):
            mod.ensure_empty_course(client, snapshot(), apply=True)
        self.assertEqual(client.doc["title"], "Manual title")
        self.assertEqual(client.writes, [])

    def test_wrong_target_or_source_account_is_rejected_before_requests(self):
        for kind in ("client", "account", "origin"):
            client, record = Client(), snapshot()
            if kind == "client":
                client.site = "my-lk.mv-centr.ru"
            else:
                record[kind] = "mv-centr" if kind == "account" else "https://shop.mv-centr.ru"
            with self.subTest(kind=kind), self.assertRaises((Review, Stop)):
                mod.ensure_empty_course(client, record, apply=True)
            self.assertEqual(client.reads, [])
            self.assertEqual(client.writes, [])

    def test_unverified_or_failed_capture_cannot_create_course(self):
        for key, value in (("verified", False), ("verified", 1), ("error", "source_auth_error")):
            client, record = Client(), snapshot()
            record[key] = value
            with self.subTest(key=key, value=value), self.assertRaises(Review):
                mod.ensure_empty_course(client, record, apply=True)
            self.assertEqual(client.reads, [])
            self.assertEqual(client.writes, [])

    def test_all_three_empty_arrays_and_explicit_reason_are_required(self):
        for key, value in (("lesson_ids", [1]), ("lessons", [{"id": 1}]), ("tree", [{"group": "unknown"}]), ("empty_reason", None)):
            client, record = Client(), snapshot()
            record["parsed"][key] = value
            with self.subTest(key=key), self.assertRaises(Review):
                mod.ensure_empty_course(client, record, apply=True)
            self.assertEqual(client.reads, [])
            self.assertEqual(client.writes, [])

    def test_parser_context_is_rechecked_instead_of_trusting_empty_claim(self):
        client, record = Client(), snapshot()
        record["html"] = record["html"].replace('value="4"', 'value="5"')
        with self.assertRaises(Review):
            mod.ensure_empty_course(client, record, apply=True)
        self.assertEqual(client.reads, [])

    def test_foreign_numeric_route_is_not_reused(self):
        client = Client()
        client.foreign_number = {**client.document(), "custom_avo_account": "mv-centr"}
        with self.assertRaises(Review):
            mod.ensure_empty_course(client, snapshot(), apply=True)
        self.assertEqual(client.writes, [])

    def test_existing_published_or_open_self_enrollment_is_not_changed(self):
        for key, value in (("published", 1), ("disable_self_learning", 0)):
            client = Client()
            client.doc = client.document()
            client.doc[key] = value
            with self.subTest(key=key), self.assertRaises(Review):
                mod.ensure_empty_course(client, snapshot(), apply=True)
            self.assertEqual(client.writes, [])

    def test_existing_lessons_or_student_rights_are_not_removed(self):
        for doctype in ("Course Lesson", "LMS Enrollment", "LMS Access Grant"):
            client = Client()
            client.doc = client.document()
            client.links[doctype] = True
            with self.subTest(doctype=doctype), self.assertRaises(Review):
                mod.ensure_empty_course(client, snapshot(), apply=True)
            self.assertEqual(client.writes, [])

    def test_concurrent_creation_stops_before_mutation(self):
        client = Client()
        client.concurrent_create = True
        with self.assertRaisesRegex(Stop, "empty_course_target_changed"):
            mod.ensure_empty_course(client, snapshot(), apply=True)
        self.assertEqual(client.writes, [])

    def test_uncertain_commit_and_failed_readback_stop_without_remote_body(self):
        for attribute in ("write_fails", "corrupt_created"):
            client = Client()
            setattr(client, attribute, True)
            with self.subTest(attribute=attribute), self.assertRaisesRegex(Stop, "empty_course_write_uncertain") as raised:
                mod.ensure_empty_course(client, snapshot(), apply=True)
            self.assertEqual(len(client.writes), 1)
            self.assertNotIn("PRIVATE", str(raised.exception))

    def test_mutation_guard_refuses_extra_fields(self):
        client = Client()
        with self.assertRaisesRegex(Stop, "empty_course_mutation_not_allowed"):
            mod._create(client, {"title": "Synthetic", "published": 1})
        self.assertEqual(client.writes, [])


if __name__ == "__main__":
    unittest.main()

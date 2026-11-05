"""Synthetic unit checks: no network, Frappe site, or real course data."""
import base64
import io
import json
import sys
import types
import unittest
from unittest.mock import patch

from PIL import Image

fake = types.ModuleType("frappe")
fake.whitelist = lambda **kwargs: lambda f: f
fake.PermissionError = PermissionError
sys.modules.setdefault("frappe", fake)
from lms.lms import avo_import as module


def payload():
    return {"account": "mv-centr", "source_origin": "https://shop.mv-centr.ru", "course_id": 5, "lesson_id": 13,
            "course_title": "Example course", "lesson_title": "Example lesson",
            "format": "preview", "content": [
                {"type": "image", "image_key": "one", "caption": "A screenshot"},
                {"type": "video_pair", "players": [
                    {"provider": "youtube", "url": "https://youtu.be/abcdefghijk"},
                    {"provider": "rutube", "url": "https://rutube.ru/video/0123456789abcdef0123456789abcdef/"}]}]}


def png():
    out = io.BytesIO()
    Image.new("RGB", (2, 2), "red").save(out, format="PNG")
    return base64.b64encode(out.getvalue()).decode()


class Meta:
    def has_field(self, name):
        return name in ("custom_avo_id", "custom_avo_account")


class ImportTests(unittest.TestCase):
    def test_saved_jpeg_must_match_original_or_exact_frappe_exif_transform(self):
        import hashlib
        image={'name':'avo-example.jpg','bytes':b'original','sha256':hashlib.sha256(b'original').hexdigest()}
        with patch.object(module,'_stripped_jpeg',return_value=b'normalized'):
            self.assertTrue(module._image_matches(image,b'original'))
            self.assertTrue(module._image_matches(image,b'normalized'))
            self.assertFalse(module._image_matches(image,b'different'))
            image['name']='avo-example.png'
            self.assertFalse(module._image_matches(image,b'normalized'))

    def test_spacer_cannot_be_imported_without_the_frontend_renderer(self):
        p = payload()
        p['format'] = 'ape'
        p.pop('content')
        from pathlib import Path
        fixture = json.loads((Path(__file__).parent / 'testdata/avo_spacer.json').read_text(encoding='utf-8'))
        p['ape'] = {'name': 'page', 'children': [fixture]}
        with patch.object(module, '_take_lock', side_effect=AssertionError('lock taken')):
            result = module.import_lesson(p, dry_run=False)
        self.assertFalse(result['ready'])
        self.assertIn('spacer_renderer_not_installed', result['issues'])

    def test_iomp_site_account_mapping_and_isolation(self):
        p = payload()
        p.update(account='iomp', source_origin='https://shop.iomp.ru')
        with self.assertRaisesRegex(ValueError, 'site_account_mismatch'):
            module.import_lesson(p, {'one': png()})
        module.frappe.local.site = 'my-lk.iomp.ru'
        self.assertTrue(module.import_lesson(p, {'one': png()})['ready'])
        p['source_origin'] = 'https://shop.mv-centr.ru'
        with self.assertRaisesRegex(ValueError, 'site_account_mismatch'):
            module.import_lesson(p, {'one': png()})

    def test_ape_image_must_match_supplied_file(self):
        p = payload()
        p['format'] = 'ape'
        p.pop('content')
        p['ape'] = {'name':'page', 'children':[{'name':'image', 'id':'one', 'fields':{'imageSrc':'https://example.test/a.jpg'}}]}
        with self.assertRaisesRegex(ValueError, 'image_keys_mismatch'):
            module._plan(p, {})
        self.assertTrue(module._plan(p, module._images({'one':png()}))['ready'])

    def setUp(self):
        module.frappe.local = types.SimpleNamespace(site="my-lk.mv-centr.ru")
        module.frappe.only_for = lambda role: self.assertEqual(role, "System Manager")
        module.frappe.get_meta = lambda doctype: Meta()
        module.frappe.get_all = lambda *args, **kwargs: []

    def test_image_validation_and_private_preview(self):
        prepared = module._images({"one": png()})
        plan = module._plan(payload(), prepared)
        self.assertTrue(plan["ready"])
        self.assertTrue(plan["blocks"][0]["data"]["url"].startswith("/private/files/avo-"))
        for data in ({"one": "not base64"}, {"../bad": png()}, {"one": base64.b64encode(b"not image").decode()}):
            with self.assertRaises(ValueError):
                module._images(data)
        with self.assertRaises(ValueError):
            module._plan(payload(), {})

    def test_dry_run_is_read_only_and_reports_unverified(self):
        module.frappe.get_doc = lambda *a, **k: self.fail("dry run wrote or opened a document")
        result = module.import_lesson(payload(), {"one": png()})
        self.assertTrue(result["dry_run"])
        self.assertTrue(result["ready"])
        self.assertFalse(result["source_complete"])
        self.assertEqual(result["action"], "create_course_and_lesson")

    def test_account_and_schema_rejected_before_write(self):
        p = payload()
        p["account"] = "mastervision"
        with self.assertRaisesRegex(ValueError, "site_account_mismatch"):
            module.import_lesson(p, {"one": png()}, dry_run=False)
        module.frappe.get_meta = lambda doctype: types.SimpleNamespace(has_field=lambda field: False)
        with self.assertRaisesRegex(ValueError, "mapping_schema_missing"):
            module.import_lesson(payload(), {"one": png()}, dry_run=False)

    def test_unsupported_source_does_not_take_lock_or_write(self):
        p = payload()
        p["content"][1]["players"] = []
        with patch.object(module, "_take_lock", side_effect=AssertionError("lock taken")):
            result = module.import_lesson(p, {"one": png()}, dry_run=False)
        self.assertFalse(result["ready"])
        self.assertIn("video_pair_incomplete", result["issues"])

    def test_fingerprint_changes_when_source_or_image_changes(self):
        p = payload()
        image = module._images({"one": png()})
        first = module._fingerprint(p, image)
        self.assertEqual(first, module._fingerprint(p, image))
        p["lesson_title"] = "changed"
        self.assertNotEqual(first, module._fingerprint(p, image))

    def test_lock_released_only_on_commit_or_rollback(self):
        calls, on_commit, on_rollback = [], [], []
        db = types.SimpleNamespace(sql=lambda query, args: calls.append(query) or [(1,)],
              after_commit=types.SimpleNamespace(add=on_commit.append),
              after_rollback=types.SimpleNamespace(add=on_rollback.append))
        module.frappe.db = db
        module._take_lock()
        self.assertEqual(len(calls), 1)
        self.assertEqual(len(on_commit), 1)
        self.assertEqual(len(on_rollback), 1)
        on_commit[0]()
        self.assertIn("RELEASE_LOCK", calls[-1])

    def test_replay_checks_snapshot_content_and_lesson(self):
        source = payload()
        prepared = module._images({"one": png()})
        digest = module._fingerprint(source, prepared)
        image_url = "/private/files/" + prepared["one"]["name"]
        normalized = module.plan_import(source, {"one": image_url})
        lesson = types.SimpleNamespace(name="lesson", course="course", title=source["lesson_title"],
            content=json.dumps({"blocks": normalized["blocks"], "version": "2.29.0"}),
            chapter="chapter", is_draft=1, include_in_preview=0, body="",
            check_permission=lambda perm: None)
        course = types.SimpleNamespace(name="course", title=source["course_title"], published=0,
            check_permission=lambda perm: None)
        source_file = types.SimpleNamespace(get_content=lambda encodings: module._snapshot(source))
        image_file = types.SimpleNamespace(file_url=image_url,
            get_content=lambda encodings: prepared["one"]["bytes"])
        records = {"source": source_file, "image": image_file}
        def get_all(doctype, filters, **kwargs):
            if doctype == "LMS Course":
                return [{"name": "course"}]
            if doctype == "Course Lesson":
                return [{"name": "lesson"}]
            if filters["file_name"] == "avo-source-sha256-" + digest + ".json":
                return [{"name": "source"}]
            if filters["file_name"] == prepared["one"]["name"]:
                return [{"name": "image"}]
            return []
        def get_doc(doctype, name):
            return {"LMS Course": course, "Course Lesson": lesson}.get(doctype) or records[name]
        module.frappe.get_all, module.frappe.get_doc = get_all, get_doc
        module.frappe.db = types.SimpleNamespace(count=lambda *args: 1)
        fake_utils = types.ModuleType("lms.lms.utils")
        fake_utils.sanitize_editorjs = lambda value: value
        with patch.dict(sys.modules, {"lms.lms.utils": fake_utils}):
            self.assertEqual(module._lookup(normalized, digest, source, prepared)[2], "already_imported")
            lesson.title = "Changed outside the importer"
            with self.assertRaisesRegex(ValueError, "existing_lesson_conflict"):
                module._lookup(normalized, digest, source, prepared)

    def test_two_simultaneous_imports_are_not_admitted(self):
        module.frappe.db = types.SimpleNamespace(sql=lambda *args: [(0,)])
        with self.assertRaisesRegex(ValueError, "import_busy"):
            module._take_lock()


if __name__ == "__main__":
    unittest.main()

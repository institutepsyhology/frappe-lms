"""Check archive handling using small, ordinary packages and temporary limits."""

import json
import tempfile
import unittest
import zipfile
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from lms.lms import api, course_import_export as importer


class ArchiveTests(unittest.TestCase):
	def setUp(self):
		tmp = tempfile.TemporaryDirectory()
		self.addCleanup(tmp.cleanup)
		self.site = Path(tmp.name)
		self.path = self.site / "lesson.zip"
		self.file = SimpleNamespace(name="example", get_full_path=lambda: str(self.path))
		self.framework = SimpleNamespace(
			get_site_path=lambda *parts: str(self.site.joinpath(*parts)),
			get_doc=lambda *_: self.file,
			throw=Mock(side_effect=ValueError),
			ValidationError=ValueError,
			log_error=Mock(),
		)
		for module in (importer, api):
			self.enterContext(patch.object(module, "frappe", self.framework))
			self.enterContext(patch.object(module, "_", str))
		self.enterContext(patch.object(importer, "is_safe_path", return_value=True))
		self.enterContext(patch.object(api, "filelock", side_effect=lambda *_: nullcontext()))
		self.enterContext(patch.object(importer.shutil, "disk_usage", return_value=SimpleNamespace(free=8 * 1024**3)))

	def make_zip(self, **files):
		with zipfile.ZipFile(self.path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
			for name, data in files.items():
				archive.writestr(name, data)

	def test_import_preserves_course_and_uses_local_chapter_settings(self):
		stored = {}
		doc = SimpleNamespace(update=stored.update, insert=Mock())
		self.framework.new_doc = lambda *_: doc
		self.make_zip(**{"course.json": '{"title":"Sample"}', "chapters/demo.json": json.dumps({
			"title": "Introduction", "is_scorm_package": 1, "scorm_package": "sample.zip",
			"scorm_package_path": "example", "manifest_file": "imsmanifest.xml", "launch_file": "index.html",
		})})
		with zipfile.ZipFile(self.path) as archive:
			importer.validate_archive(archive)
			self.assertEqual(importer.read_json_from_zip(archive, "course.json"), {"title": "Sample"})
			self.assertEqual(importer.create_chapter_docs(archive, "sample"), [doc])
		self.assertEqual(stored, {"title": "Introduction"})
		self.assertEqual(doc.course, "sample")
		doc.insert.assert_called_once()

	def test_limits_stop_import_before_writing(self):
		self.make_zip(**{"course.json": '{"title":"Sample"}', "notes.txt": "notes"})
		for key, limit in (("MAX_ARCHIVE_MEMBERS", 1), ("MAX_ARCHIVE_BYTES", 8), ("MAX_ARCHIVE_JSON_BYTES", 8)):
			with self.subTest(key=key), patch.object(importer, key, limit), patch.object(importer, "create_assets") as write:
				with self.assertRaises(ValueError):
					importer.import_course_zip(self.path.name)
				write.assert_not_called()

	def test_small_disk_stops_import_before_writing(self):
		self.make_zip(**{"course.json": '{"title":"Sample"}'})
		with patch.object(importer.shutil, "disk_usage", return_value=SimpleNamespace(free=1024)), patch.object(importer, "create_assets") as write:
			with self.assertRaises(ValueError):
				importer.import_course_zip(self.path.name)
			write.assert_not_called()

	def test_normal_scorm_replacement_and_cleanup(self):
		self.make_zip(**{"index.html": "First lesson", "handout.txt": "Notes"})
		target = Path(api.extract_package("course", "chapter", self.file))
		self.make_zip(**{"index.html": "Revised lesson"})
		with patch.object(zipfile.ZipFile, "extractall", side_effect=OSError("simulated write failure")):
			with self.assertRaises(OSError):
				api.extract_package("course", "chapter", self.file)
		self.assertEqual((target / "index.html").read_text(), "First lesson")
		self.assertEqual((target / "handout.txt").read_text(), "Notes")
		with patch.object(importer, "MAX_ARCHIVE_BYTES", 3), self.assertRaises(ValueError):
			api.extract_package("course", "chapter", self.file)
		self.assertEqual((target / "index.html").read_text(), "First lesson")
		self.assertEqual(Path(api.extract_package("course", "chapter", self.file)), target)
		self.assertEqual((target / "index.html").read_text(), "Revised lesson")
		self.assertFalse((target / "handout.txt").exists())

	def test_package_with_launch_document_is_published(self):
		manifest = ('<manifest xmlns:adlcp="urn:example"><resources>'
		            '<resource adlcp:scormtype="sco" href="index.html"/></resources></manifest>')
		self.make_zip(**{"lesson/imsmanifest.xml": manifest, "lesson/index.html": "Sample"})
		target, document, launch = api._extract_scorm_package("course", "chapter", self.file, require_launch=True)
		self.assertEqual(Path(document), Path(target) / "lesson" / "imsmanifest.xml")
		self.assertEqual(Path(launch).read_text(), "Sample")
		self.make_zip(**{"lesson/imsmanifest.xml": manifest, "lesson/notes.txt": "Incomplete revision"})
		with self.assertRaises(ValueError):
			api._extract_scorm_package("course", "chapter", self.file, require_launch=True)
		self.assertEqual(Path(launch).read_text(), "Sample")


if __name__ == "__main__":
	unittest.main()

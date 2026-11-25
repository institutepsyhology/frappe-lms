"""Exercise the course archive using disposable files and synthetic document permissions."""

import io
import json
import tempfile
import unittest
import zipfile
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from lms.lms import course_import_export as exporter


class Doc(SimpleNamespace):
	def as_dict(self):
		return {"name": self.name}


class TestCourseExportFiles(unittest.TestCase):
	def setUp(self):
		folder = tempfile.TemporaryDirectory()
		self.addCleanup(folder.cleanup)
		self.site = Path(folder.name)
		self.public = self.site / "public" / "files"
		self.private = self.site / "private" / "files"
		self.public.mkdir(parents=True)
		self.private.mkdir(parents=True)
		self.course = Doc(name="demo-course", chapters=[Doc(chapter="demo-chapter")], instructors=[], evaluator=None, image="")
		self.lesson = Doc(name="demo-lesson", content="")
		self.chapter = Doc(name="demo-chapter")
		self.files = []
		self.response = SimpleNamespace()
		self.permission = Mock(side_effect=lambda _type, _action, doc: doc.readable)
		self.frappe = SimpleNamespace(
			get_all=self.lookup,
			get_doc=self.document,
			get_site_path=lambda *parts: str(self.site.joinpath(*parts)),
			has_permission=self.permission,
			utils=SimpleNamespace(now_datetime=datetime.now),
			local=SimpleNamespace(response=self.response),
			enqueue=Mock(),
			throw=Mock(side_effect=ValueError),
			ValidationError=ValueError,
		)
		for key, value in (("frappe", self.frappe), ("_", str),
		                   ("get_files_path", lambda is_private: str(self.private if is_private else self.public))):
			replacement = patch.object(exporter, key, value)
			replacement.start()
			self.addCleanup(replacement.stop)

	def document(self, doctype, name):
		if doctype == "File":
			return next(file for file in self.files if file.name == name)
		return {"LMS Course": self.course, "Course Lesson": self.lesson, "Course Chapter": self.chapter}[doctype]

	def lookup(self, doctype, filters, **fields):
		if doctype == "Course Lesson":
			return [self.lesson.name]
		self.assertEqual(doctype, "File")
		self.assertEqual(filters["is_folder"], 0)
		self.assertTrue(fields["order_by"].startswith("creation asc"))
		return [file for file in self.files if file.file_url.casefold() == filters["file_url"].casefold()]

	def file(self, url, data, attached_to=None, readable=False):
		parent = self.private if url.startswith("/private/") else self.public
		path = parent / url.rsplit("/", 1)[1]
		path.write_bytes(data)
		doc = Doc(name=f"file-{len(self.files)}", file_url=url, attached_to_doctype="Course Lesson",
		          attached_to_name=attached_to, readable=readable, get_full_path=lambda: str(path))
		self.files.append(doc)
		return doc

	def reference(self, *urls):
		self.lesson.content = json.dumps({"blocks": [{"type": "upload", "data": {"file_url": url}} for url in urls]})

	def test_download_includes_only_permitted_bytes_and_preserves_legacy_format(self):
		attached = self.file("/private/files/workbook.pdf", b"own lesson material", self.lesson.name)
		shared = self.file("/files/handout.pdf", b"allowed reference", readable=True)
		other = self.file("/private/files/other.pdf", b"other lesson material", "another-lesson")
		self.reference(attached.file_url, shared.file_url, other.file_url, attached.file_url, None, {})
		exporter.export_course_zip(self.course.name)
		with zipfile.ZipFile(io.BytesIO(self.response.filecontent)) as archive:
			self.assertEqual(sorted(n for n in archive.namelist() if n.startswith("assets/")),
			                 ["assets/handout.pdf", "assets/workbook.pdf"])
			self.assertEqual(archive.read("assets/handout.pdf"), b"allowed reference")
			self.assertEqual(archive.read("assets/workbook.pdf"), b"own lesson material")
			self.assertEqual(json.loads(archive.read("course.json"))["name"], self.course.name)
			self.assertIn("lessons/demo-lesson.json", archive.namelist())
			self.assertIn("chapters/demo-chapter.json", archive.namelist())
		self.assertEqual(self.response.type, "download")
		self.frappe.enqueue.assert_called_once()

	def test_canonical_name_and_exact_file_record_are_required(self):
		doc = self.file("/private/files/report.pdf", b"synthetic", self.lesson.name)
		self.assertIsNone(exporter.get_exportable_file("/private/files/Report.pdf", {("Course Lesson", self.lesson.name)}))
		doc.get_full_path = lambda: str(self.private / "another.pdf")
		(self.private / "another.pdf").write_bytes(b"synthetic alternate")
		self.assertIsNone(exporter.get_local_file_path(doc))

	def test_later_attachment_does_not_change_original_permissions(self):
		first = self.file("/private/files/shared.pdf", b"synthetic", "other-lesson")
		self.files.append(Doc(**{**vars(first), "name": "later-record", "attached_to_name": self.lesson.name}))
		self.reference(first.file_url)
		self.assertEqual(exporter.get_course_assets(self.course, [self.lesson], [], []), [])
		self.permission.assert_called_once_with("File", "read", doc=first)

	def test_ambiguous_archive_stops_before_writing(self):
		private = self.file("/private/files/guide.pdf", b"private sample", self.lesson.name)
		public = self.file("/files/guide.pdf", b"public sample", readable=True)
		self.reference(private.file_url, public.file_url)
		with patch.object(exporter, "create_course_zip") as write:
			with self.assertRaises(ValueError):
				exporter.export_course_zip(self.course.name)
			write.assert_not_called()


if __name__ == "__main__":
	unittest.main()

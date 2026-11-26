"""Exercise chapter operations with real ZIPs, the renderer and a temporary site lock."""

import inspect
import tempfile
import unittest
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import frappe
from frappe.utils import synchronization
from werkzeug.test import EnvironBuilder

from lms import page_renderers, scorm_paths
from lms.lms import api, course_import_export
from lms.lms.doctype.course_chapter import course_chapter


class Callbacks(list):
	add = list.append


class ChapterPackageOwnershipTests(unittest.TestCase):
	def setUp(self):
		self.site = Path(self.enterContext(tempfile.TemporaryDirectory()))
		self.course = Mock()
		self.chapters = {}
		self.files = {}
		self.after_commit, self.after_rollback = Callbacks(), Callbacks()
		db = SimpleNamespace(
			get_value=self.get_value, delete=self.delete_rows, exists=lambda dt, key: key in self.files,
			after_commit=self.after_commit, after_rollback=self.after_rollback,
		)
		self.framework = SimpleNamespace(
			get_site_path=self.site_path, _dict=frappe._dict, get_doc=self.get_doc, new_doc=self.new_doc,
			get_all=self.get_all, has_permission=Mock(return_value=True), db=db, log_error=Mock(),
			PermissionError=frappe.PermissionError, ValidationError=frappe.ValidationError,
			throw=lambda msg, exc=ValueError: self.raise_error(msg, exc),
			local=SimpleNamespace(request=SimpleNamespace(environ=EnvironBuilder().get_environ())),
		)
		for module in (api, course_import_export, page_renderers, scorm_paths):
			self.enterContext(patch.object(module, "frappe", self.framework))
		for module in (api, course_import_export):
			self.enterContext(patch.object(module, "_", str))
		self.enterContext(patch.object(api, "can_modify_course", return_value=True))
		self.enterContext(patch.object(api, "add_lesson", side_effect=self.add_lesson))
		self.enterContext(patch.object(course_chapter, "get_scorm_lesson", side_effect=lambda key: self.chapters[key].lessons[0]))
		self.access = self.enterContext(patch.object(course_chapter, "resolve_scorm_access", return_value=frappe._dict(can_access=True, locked=False)))
		self.enterContext(patch.object(course_import_export.shutil, "disk_usage", return_value=SimpleNamespace(free=4 * 1024**3)))
		self.enterContext(patch.object(synchronization, "get_site_path", side_effect=self.site_path))
		self.site.joinpath(synchronization.LOCKS_DIR).mkdir(parents=True)
		self.lock = self.enterContext(patch.object(api, "filelock", wraps=synchronization.filelock))

	@staticmethod
	def raise_error(message, exception):
		raise exception(message)

	def site_path(self, *parts):
		return str(self.site.joinpath(*parts))

	def get_doc(self, doctype, key, **kwargs):
		if doctype == "File":
			return self.files[key]
		if doctype == "LMS Course":
			return self.course
		self.assertEqual(doctype, "Course Chapter")
		return self.chapters[key]

	def new_doc(self, doctype):
		self.assertEqual(doctype, "Course Chapter")
		name = f"record-{len(self.chapters) + 1}"
		row = frappe._dict(name=name, lessons=[], save=Mock(), check_permission=Mock())
		row.insert = lambda: self.chapters.update({row.name: row})
		return row

	def get_value(self, doctype, key, fields, **kwargs):
		self.assertEqual(doctype, "Course Chapter")
		return frappe._dict({field: self.chapters[key].get(field) for field in fields})

	def get_all(self, doctype, filters, **kwargs):
		if doctype == "Course Chapter":
			return [row for row in self.chapters.values() if row.course == filters["course"]]
		self.assertIn(doctype, ("Course Lesson", "Chapter Reference"))
		return []

	def delete_rows(self, doctype, key):
		if doctype == "Course Chapter":
			del self.chapters[key]

	def add_lesson(self, title, chapter, course, idx):
		self.chapters[chapter].lessons.append("lesson-" + chapter)

	def upload(self, key, lesson):
		path = self.site / (key + ".zip")
		with zipfile.ZipFile(path, "w") as archive:
			archive.writestr("imsmanifest.xml", '<manifest xmlns:adlcp="urn:sample"><resources><resource adlcp:scormtype="sco" href="slides/index.html"/></resources></manifest>')
			archive.writestr("slides/index.html", lesson)
			archive.writestr("slides/notes.txt", "notes")
		self.files[key] = SimpleNamespace(name=key, get_full_path=lambda: str(path))
		return {"name": key}

	def save(self, title, package=None, name=None):
		# The HTTP decorator belongs to Frappe; exercise the actual application method body.
		return inspect.unwrap(api.upsert_chapter)(title, "sample-course", bool(package), package, name)

	def finish(self, callbacks):
		for run in list(callbacks):
			run()
		self.after_commit.clear()
		self.after_rollback.clear()

	def read(self, url):
		player = page_renderers.SCORMRenderer.__new__(page_renderers.SCORMRenderer)
		player.path = url
		self.assertTrue(player.can_render())
		response = player.render()
		self.assertEqual(response.headers["Cache-Control"], "private, no-store")
		try:
			return b"".join(response.response)
		finally:
			response.close()

	def test_ordinary_chapter_can_be_created_and_renamed(self):
		chapter = self.save("Introduction")
		self.assertEqual(chapter.course, "sample-course")
		self.assertEqual(chapter.lessons, [])
		self.assertIs(self.save("Orientation", name=chapter.name), chapter)
		self.assertEqual(chapter.title, "Orientation")
		self.course.append.assert_called_once_with("chapters", {"chapter": chapter.name})
		chapter.check_permission.assert_called_once_with("write")
		self.lock.assert_not_called()

	def test_equal_titles_have_separate_packages_and_lesson_permissions(self):
		first_upload = self.upload("first", "One")
		first = self.save("Workshop", first_upload)
		self.finish(self.after_commit)
		second = self.save("Workshop", self.upload("second", "Two"))
		self.finish(self.after_commit)
		self.assertNotEqual(first.scorm_package_path, second.scorm_package_path)
		self.assertEqual(self.read(first.launch_file), b"One")
		self.assertEqual(self.read(second.launch_file), b"Two")
		self.assertEqual(self.read(first.scorm_package_path + "/notes.txt"), b"notes")
		link = first.launch_file
		self.save("Renamed", first_upload, first.name)
		self.assertEqual(first.launch_file, link)
		self.access.return_value = frappe._dict(can_access=True, locked=True)
		with self.assertRaises(frappe.PermissionError):
			self.read(link)
		self.access.assert_called_with("sample-course", first.lessons[0])
		self.lock.assert_called_with("lms-scorm-publish")
		self.framework.has_permission.assert_any_call("File", ptype="read", doc="first", throw=True)

	def test_legacy_link_resolves_the_original_package_after_rename(self):
		chapter = self.save("Old lesson")
		chapter.update(is_scorm_package=1, title="New lesson", scorm_package_path="/scorm/sample-course/Old lesson", lessons=["old-lesson"])
		index = self.site / "public/scorm/sample-course/Old lesson/index.html"
		index.parent.mkdir(parents=True)
		index.write_bytes(b"Original lesson")
		self.assertEqual(self.read("/scorm/sample-course/Old%20lesson/"), b"Original lesson")
		self.access.assert_called_with("sample-course", "old-lesson")

	def test_deletion_waits_for_commit_and_preserves_the_other_chapter(self):
		first = self.save("Workshop", self.upload("first", "First"))
		self.finish(self.after_commit)
		second = self.save("Workshop", self.upload("second", "Second"))
		self.finish(self.after_commit)
		path = self.site / "private" / first.scorm_package_path.lstrip("/")
		inspect.unwrap(api.delete_chapter)(first.name)
		self.assertTrue(path.is_dir())
		self.assertEqual(len(self.after_commit), 1)
		self.finish(self.after_commit)
		self.assertFalse(path.exists())
		self.assertEqual(self.read(second.launch_file), b"Second")

	def test_failed_save_restores_previously_committed_package(self):
		chapter = self.save("Training", self.upload("one", "First"))
		self.finish(self.after_commit)
		link = chapter.launch_file
		chapter.save.side_effect = RuntimeError("Simulated save failure")
		with self.assertRaisesRegex(RuntimeError, "Simulated save failure"):
			self.save("Training", self.upload("two", "Second"), chapter.name)
		self.assertEqual(len(self.after_rollback), 1)
		self.finish(self.after_rollback)
		self.assertEqual(self.read(link), b"First")
		self.assertFalse(any((self.site / "private/scorm").glob("*.previous")))

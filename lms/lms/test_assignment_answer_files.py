import unittest
from types import SimpleNamespace
from unittest.mock import patch

from lms.lms import assignment_answer_files as binding


class TestAnswerFiles(unittest.TestCase):
	def setUp(self):
		p = patch.object(binding, "frappe")
		self.fr = p.start()
		self.addCleanup(p.stop)
		self.fr.session.user = "student"
		self.fr.db.get_value.return_value = 1
		self.fr.throw.side_effect = ValueError
		self.files = {}
		self.fr.get_all.side_effect = lambda _, **kw: [
			name for name, f in self.files.items()
			if f.file_url in kw["filters"]["file_url"][1] and f.is_private and f.owner == kw["filters"]["owner"]
		]
		self.fr.get_doc.side_effect = lambda _, name, **kw: self.files[name]
		self.fr.db.set_value.side_effect = lambda _, key, fields: vars(self.files[key]).update(fields)

	def add_file(self, name, owner="student", **overrides):
		f = SimpleNamespace(name=name, owner=owner, file_url="/private/files/" + name,
			is_private=1, attached_to_name=None, attached_to_doctype=None, attached_to_field=None)
		vars(f).update(overrides)
		self.files[name] = f
		return f

	def sync(self, current, prior=None):
		record = SimpleNamespace(name="submission", member="student", doctype="LMS Assignment Submission",
			assignment="homework", answer=current, get_doc_before_save=lambda: SimpleNamespace(answer=prior) if prior else None)
		binding.sync_answer_files(record)

	def test_multiple_files_private_and_removable(self):
		first, second = self.add_file("proof 1.pdf"), self.add_file("second.txt")
		html = 'Ответ<p><a href="/private/files/proof%201.pdf">Первый</a></p>'
		both = html + '<a href="/private/files/second.txt">Второй</a>'
		self.sync(both)
		for file in (first, second):
			self.assertEqual((file.attached_to_doctype, file.attached_to_name, file.attached_to_field, file.is_private),
							 ("LMS Assignment Submission", "submission", "answer", 1))
		self.sync(html, both)
		self.assertIsNone(second.attached_to_name)
		self.assertEqual(first.attached_to_name, "submission")

	def test_foreign_file_or_file_on_another_record_is_never_reassigned(self):
		for owner, record in [("other", None), ("student", "other-submission")]:
			with self.subTest(owner=owner, record=record):
				f = self.add_file("file.pdf", owner=owner, attached_to_name=record)
				with self.assertRaises(ValueError):
					self.sync('<a href="/private/files/file.pdf">Файл</a>')
				self.assertEqual(f.attached_to_name, record)

	def test_grade_does_not_change_files_and_teacher_cannot_attach_as_student(self):
		f = self.add_file("student.pdf")
		self.fr.session.user = "moderator"
		html = '<a href="/private/files/student.pdf">Файл</a>'
		self.sync(html, html)
		self.fr.db.set_value.assert_not_called()
		with self.assertRaises(ValueError):
			self.sync(html)
		self.assertIsNone(f.attached_to_doctype)

	def test_plain_text_assignment_retains_image_and_skips_file_links(self):
		self.fr.db.get_value.return_value = 0
		image, extra = self.add_file("image.png"), self.add_file("file.pdf")
		self.sync('<img src="/private/files/image.png"><a href="/private/files/file.pdf">Файл</a>')
		self.assertEqual(image.attached_to_name, "submission")
		self.assertIsNone(extra.attached_to_name)

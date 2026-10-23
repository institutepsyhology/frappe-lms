from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from lms.lms.api import get_translations


class TestTranslationLanguage(FrappeTestCase):
	def assert_language(self, user, user_language, system_language, expected):
		with (
			patch("lms.lms.api.frappe.session", frappe._dict(user=user)),
			patch("lms.lms.api.frappe.db.get_value", return_value=user_language) as user_value,
			patch("lms.lms.api.frappe.db.get_single_value", return_value=system_language) as system_value,
			patch("lms.lms.api.get_all_translations", return_value={"Courses": "Курсы"}) as catalog,
		):
			self.assertEqual(get_translations(), {"Courses": "Курсы"})
			catalog.assert_called_once_with(expected)
			if user == "Guest":
				user_value.assert_not_called()
			else:
				user_value.assert_called_once_with("User", user, "language")
			if user_language and user != "Guest":
				system_value.assert_not_called()
			else:
				system_value.assert_called_once_with("System Settings", "language")

	def test_user_language_takes_precedence(self):
		self.assert_language("student@example.test", "de", "ru", "de")

	def test_user_without_language_uses_system_language(self):
		self.assert_language("student@example.test", None, "ru", "ru")

	def test_empty_user_language_uses_system_language(self):
		self.assert_language("student@example.test", "", "ru", "ru")

	def test_guest_uses_system_language(self):
		self.assert_language("Guest", None, "ru", "ru")

	def test_missing_languages_use_english(self):
		self.assert_language("student@example.test", None, None, "en")

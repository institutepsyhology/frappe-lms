"""Safety checks for title-length migration without a database."""
import sys
import types
import unittest
from unittest.mock import patch

import frappe


class TitleSchemaTests(unittest.TestCase):
    def test_conflicting_setter_stops_before_any_write(self):
        from lms.lms import avo_title_schema as schema
        fake=types.SimpleNamespace(local=types.SimpleNamespace(site='my-lk.mv-centr.ru'))
        fake.get_all=lambda *a,**k:[types.SimpleNamespace(value='200')]
        with patch.object(schema,'frappe',fake),patch.object(schema,'_set_length',side_effect=AssertionError('write attempted')):
            with self.assertRaisesRegex(ValueError,'conflicting_title_length_setting'):schema.execute()

    def test_unexpected_site_stops_before_any_query(self):
        from lms.lms import avo_title_schema as schema
        fake=types.SimpleNamespace(local=types.SimpleNamespace(site='unrelated.example'))
        with patch.object(schema,'frappe',fake):
            with self.assertRaisesRegex(ValueError,'unexpected_site'):schema.execute()

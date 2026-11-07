"""Tests for safe, idempotent widening of lesson content."""
import importlib
import sys
import types
import unittest
from unittest.mock import patch


class ContentSchemaTests(unittest.TestCase):
    def test_widen_and_repeat_without_modifying_content(self):
        state={'setting':False,'column':'text','updates':0}
        db=types.SimpleNamespace(commit=lambda:None,
            sql=lambda *a,**k:[(state['column'],)],
            updatedb=lambda _:state.update(column='longtext',updates=state['updates']+1))
        fake=types.SimpleNamespace(local=types.SimpleNamespace(site='my-lk.mv-centr.ru'),db=db,
            get_all=lambda *a,**k:[types.SimpleNamespace(value='Long Text')] if state['setting'] else [],
            get_meta=lambda *a,**k:types.SimpleNamespace(get_field=lambda _:types.SimpleNamespace(fieldtype='Long Text' if state['setting'] else 'Text')),
            clear_cache=lambda **k:None)
        with patch.dict(sys.modules,{'frappe':fake}):
            sys.modules.pop('lms.lms.avo_content_schema',None)
            schema=importlib.import_module('lms.lms.avo_content_schema')
            with patch.object(schema,'_set_long_text',side_effect=lambda:state.update(setting=True)) as setter:
                schema.execute();schema.execute()
                self.assertEqual(setter.call_count,1)
                self.assertEqual(state['column'],'longtext')
                self.assertEqual(state['updates'],2)

    def test_conflicting_setter_stops_before_database_changes(self):
        fake=types.SimpleNamespace(local=types.SimpleNamespace(site='my-lk.mv-centr.ru'),
            get_all=lambda *a,**k:[types.SimpleNamespace(value='Data')])
        with patch.dict(sys.modules,{'frappe':fake}):
            sys.modules.pop('lms.lms.avo_content_schema',None)
            schema=importlib.import_module('lms.lms.avo_content_schema')
            with patch.object(schema,'_set_long_text',side_effect=AssertionError('unexpected write')):
                with self.assertRaisesRegex(ValueError,'conflicting_content_field_setting'):schema.execute()

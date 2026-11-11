import importlib.util
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch


class MarketingTest(unittest.TestCase):
    def setUp(self):
        self.queries = []
        self.frappe = types.ModuleType('frappe')
        self.frappe.whitelist = lambda **kw: lambda fn: fn
        self.frappe.session = types.SimpleNamespace(user='Administrator')
        self.frappe.local = types.SimpleNamespace(site='my-lk.mv-centr.ru')
        self.frappe.PermissionError = PermissionError
        self.frappe.ValidationError = ValueError
        self.frappe.throw = lambda msg, cls: (_ for _ in ()).throw(cls(msg))
        self.frappe.parse_json = lambda x: x
        self.frappe.db = types.SimpleNamespace(sql=lambda query, args: self.queries.append((query,args)) or [])
        self.modules = patch.dict(sys.modules, {'frappe':self.frappe}); self.modules.start()
        self.addCleanup(self.modules.stop)
        spec = importlib.util.spec_from_file_location('avo_marketing', Path(__file__).with_name('avo_marketing.py'))
        self.m = importlib.util.module_from_spec(spec); spec.loader.exec_module(self.m)

    def test_positive_flags_never_clear_existing_preference(self):
        self.assertEqual(self.m.apply_source_optouts('mv-centr',['10','11']), {'processed':2})
        self.assertEqual(len(self.queries),4)
        for sql, _ in self.queries:
            self.assertNotIn('set custom_no_marketing_email=0', sql.lower())
        with self.assertRaises(PermissionError): self.m.apply_source_optouts('iomp',['10'])
        with self.assertRaises(ValueError): self.m.apply_source_optouts('mv-centr',["1' OR 1=1"])

    def test_group_member_is_blocked_if_any_contact_has_opted_out(self):
        doc = types.SimpleNamespace(email='shared@example.invalid', unsubscribed=0)
        with patch.object(self.m, 'is_blocked', return_value=True):
            self.m.protect_group_member(doc)
        self.assertEqual(doc.unsubscribed,1)
        doc.unsubscribed=0
        with patch.object(self.m, 'is_blocked', return_value=False):
            self.m.protect_group_member(doc)
        self.assertEqual(doc.unsubscribed,0)

    def test_editing_any_contact_with_email_protects_existing_group(self):
        class Doc(dict):
            doctype='Contact'
        self.m.protect_document(Doc(custom_no_marketing_email=1, email_id='shared@example.invalid'))
        self.assertEqual(len(self.queries),1)
        self.assertIn('unsubscribed=1',self.queries[0][0])


if __name__ == '__main__': unittest.main()

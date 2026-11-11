import importlib.util
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch


class ContactResolverTest(unittest.TestCase):
    def setUp(self):
        self.frappe = types.ModuleType('frappe')
        self.frappe.whitelist = lambda *a, **kw: lambda fn: fn
        self.frappe._ = lambda x: x
        self.frappe.ValidationError = ValueError
        self.frappe.PermissionError = PermissionError
        self.frappe.throw = lambda message, exc: (_ for _ in ()).throw(exc(message))
        self.frappe.local = types.SimpleNamespace(site='my-lk.mv-centr.ru')
        self.rows = {'User': [], 'Contact': []}
        self.filters = []
        def get_all(kind, **kwargs):
            self.filters.append(kwargs['filters'])
            return self.rows[kind]
        self.frappe.get_all = get_all
        with patch.dict(sys.modules, {'frappe': self.frappe}):
            spec = importlib.util.spec_from_file_location('contact_resolver', Path(__file__).with_name('avo_contact_card.py'))
            self.module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(self.module)
        self.module._check_access = lambda: None

    def test_user_and_contact_without_email_resolve_by_account_and_id(self):
        self.rows['User'] = [types.SimpleNamespace(name='one@example.test')]
        self.assertEqual(self.module.resolve_source_id('123')['kind'], 'User')
        self.assertTrue(all(x == {'custom_avo_account': 'mv-centr', 'custom_avo_contact_id': '123'} for x in self.filters))
        self.rows['User'] = []
        self.rows['Contact'] = [types.SimpleNamespace(name='internal-key', user=None)]
        self.assertEqual(self.module.resolve_source_id('123'), {'kind': 'Contact', 'name': 'internal-key'})

    def test_refuses_ambiguous_identity_and_invalid_id(self):
        self.rows['User'] = [types.SimpleNamespace(name='one'), types.SimpleNamespace(name='two')]
        with self.assertRaises(ValueError): self.module.resolve_source_id('123')
        for value in ('', '0', '../1', '１２', '1' * 21):
            with self.assertRaises(ValueError): self.module.resolve_source_id(value)

    def test_linked_contact_and_user_resolve_to_user_only(self):
        self.rows['User'] = [types.SimpleNamespace(name='one')]
        self.rows['Contact'] = [types.SimpleNamespace(name='c', user='one')]
        self.assertEqual(self.module.resolve_source_id('123')['kind'], 'User')
        self.rows['Contact'][0].user = 'other'
        with self.assertRaises(ValueError): self.module.resolve_source_id('123')

    def test_unknown_site_and_permission_are_rejected(self):
        self.frappe.local.site = 'unknown.example'
        with self.assertRaises(ValueError): self.module.resolve_source_id('123')
        self.module._check_access = lambda: (_ for _ in ()).throw(PermissionError())
        with self.assertRaises(PermissionError): self.module.resolve_source_id('123')


if __name__ == '__main__': unittest.main()

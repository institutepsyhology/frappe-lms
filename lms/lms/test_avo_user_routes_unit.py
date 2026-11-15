import importlib.util
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch


class Row(dict):
    __getattr__ = dict.get


class UserRouteTests(unittest.TestCase):
    def setUp(self):
        self.f = types.ModuleType('frappe')
        self.f._ = lambda s: s
        self.f.whitelist = lambda *a, **kw: lambda f: f
        self.f.local = Row(site='my-lk.mv-centr.ru')
        self.f.session = Row(user='moderator@example.test')
        self.f.ValidationError = ValueError
        self.f.PermissionError = PermissionError
        self.f.throw = lambda message, exc=ValueError: (_ for _ in ()).throw(exc(message))
        self.f.get_roles = lambda: ['Moderator']
        self.f.get_meta = lambda _: Row(has_field=lambda _: True)
        self.f.db = Row(get_value=lambda *args, **kwargs: None)
        self.f.get_all = lambda *args, **kwargs: []
        contact = types.ModuleType('lms.lms.avo_contact_card')
        contact.SITE_ACCOUNTS = {'my-lk.mv-centr.ru': 'mv-centr'}
        self.api = types.ModuleType('lms.lms.api')
        self.api.get_profile_details = lambda username: Row(name='u', username=username)
        self.api.get_members = lambda *args: [Row(name='u')]
        policy=types.ModuleType('lms.lms.staff_policy')
        policy.require_capability=lambda *a,**kw: None if 'Moderator' in self.f.get_roles() else self.f.throw('Denied',PermissionError)
        self.modules = patch.dict(sys.modules, {'frappe': self.f, 'lms.lms.api': self.api,
                                                'lms.lms.avo_contact_card': contact,'lms.lms.staff_policy':policy})
        self.modules.start()
        spec = importlib.util.spec_from_file_location('avo_user_routes_unit', Path(__file__).with_name('avo_user_routes.py'))
        self.m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.m)

    def tearDown(self):
        self.modules.stop()

    def test_moderator_resolves_only_exact_site_and_source(self):
        self.f.get_all = lambda doctype, **kw: [Row(name='u')] if doctype == 'User' and kw['filters'] == {
            'custom_avo_account': 'mv-centr', 'custom_avo_contact_id': '221910'} else []
        self.assertEqual(self.m.resolve_member('221910')['name'], 'u')
        self.f.get_roles = lambda: ['LMS Student']
        with self.assertRaises(PermissionError): self.m.resolve_member('221910')

    def test_duplicate_or_conflicting_numeric_username_fails_closed(self):
        self.f.get_all = lambda *a, **kw: [Row(name='u', username='alice')]
        self.f.db.get_value = lambda *a, **kw: 'other'
        with self.assertRaises(ValueError): self.m.get_profile_details('5')
        self.f.get_all = lambda *a, **kw: [Row(name='u'), Row(name='v')]
        with self.assertRaises(ValueError): self.m.resolve_member('5')

    def test_legacy_profile_resolves_and_returns_numeric_id_only_after_permission(self):
        self.f.db.get_value = lambda *a, **kw: Row(custom_avo_account='mv-centr', custom_avo_contact_id='5')
        self.assertEqual(self.m.get_profile_details('alice')['avo_route_id'], '5')
        self.api.get_profile_details = lambda *_: (_ for _ in ()).throw(PermissionError())
        with self.assertRaises(PermissionError): self.m.get_profile_details('alice')

    def test_moderator_gets_numeric_ids_without_cross_account_ids(self):
        self.f.get_all = lambda *a, **kw: [Row(name='u', custom_avo_contact_id='221910')]
        self.assertEqual(self.m.get_members()[0]['custom_avo_contact_id'], '221910')
        self.f.local.site = 'unknown.local'
        self.assertIsNone(self.m.get_members()[0].get('custom_avo_contact_id'))


if __name__ == '__main__': unittest.main()

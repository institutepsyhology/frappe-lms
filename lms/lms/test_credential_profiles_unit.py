import importlib.util
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch


class ProfileTest(unittest.TestCase):
    def setUp(self):
        self.f=types.ModuleType('frappe')
        self.f._=lambda s:s
        self.f.session=types.SimpleNamespace(user='staff@example.invalid')
        self.f.PermissionError=PermissionError;self.f.ValidationError=ValueError
        self.f.throw=lambda message,exc: (_ for _ in ()).throw(exc(message))
        self.f.whitelist=lambda **kwargs:lambda fn:fn
        self.f.get_roles=lambda user=None:[]
        self.f.get_meta=lambda dt:types.SimpleNamespace(has_field=lambda field:True)
        self.f.db=types.SimpleNamespace(sql=lambda sql,args:[],exists=lambda *args:True,set_value=lambda *args:None)
        self.f.only_for=lambda role: (_ for _ in ()).throw(PermissionError())
        custom=types.ModuleType('frappe.custom.doctype.custom_field.custom_field')
        custom.create_custom_fields=lambda *args,**kwargs:None
        self.modules=patch.dict(sys.modules,{'frappe':self.f,'frappe.custom.doctype.custom_field.custom_field':custom})
        self.modules.start();self.addCleanup(self.modules.stop)
        spec=importlib.util.spec_from_file_location('credential_profiles',Path(__file__).with_name('credential_profiles.py'))
        self.m=importlib.util.module_from_spec(spec);spec.loader.exec_module(self.m)

    def test_administrator_and_system_manager_authorized(self):
        self.assertTrue(self.m.can_manage_credentials('Administrator'))
        self.f.get_roles=lambda user=None:['System Manager']
        self.assertTrue(self.m.can_manage_credentials('manager@example.invalid'))

    def test_direct_role_does_not_authorize_and_profile_removal_is_immediate(self):
        self.f.get_roles=lambda user=None:['LMS Credential Manager']
        self.assertFalse(self.m.can_manage_credentials())
        self.f.db.sql=lambda sql,args:[(1,)]
        self.assertTrue(self.m.can_manage_credentials())
        self.f.db.sql=lambda sql,args:[]
        self.assertFalse(self.m.can_manage_credentials())

    def test_profile_permission_cannot_be_changed_by_staff(self):
        with self.assertRaises(PermissionError):self.m.set_profile_access('some profile',1)


if __name__=='__main__':unittest.main()

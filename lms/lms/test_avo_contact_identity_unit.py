import importlib.util
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch


class IdentityFieldsTest(unittest.TestCase):
    def test_contact_identity_is_private_unique_and_site_bound(self):
        captured=[]
        frappe=types.ModuleType('frappe')
        frappe.local=types.SimpleNamespace(site='my-lk.mv-centr.ru')
        name='frappe.custom.doctype.custom_field.custom_field'
        custom=types.ModuleType(name)
        custom.create_custom_fields=lambda fields, update:captured.append((fields,update))
        modules={k:types.ModuleType(k) for k in ['frappe.custom','frappe.custom.doctype','frappe.custom.doctype.custom_field']}
        modules.update({'frappe':frappe,name:custom})
        with patch.dict(sys.modules,modules):
            spec=importlib.util.spec_from_file_location('identity',Path(__file__).with_name('avo_contact_identity.py'))
            mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod);mod.execute()
            fields, update=captured[0]
            self.assertEqual(list(fields),['Contact'])
            self.assertTrue(update)
            self.assertTrue(all(x['permlevel']==1 for x in fields['Contact']))
            self.assertEqual(next(x for x in fields['Contact'] if x['fieldname']=='custom_avo_contact_id')['unique'],1)
            frappe.local.site='my-lk.iomp.ru'
            with self.assertRaises(RuntimeError):mod.execute()


if __name__=='__main__':unittest.main()

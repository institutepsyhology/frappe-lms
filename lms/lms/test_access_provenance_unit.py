import importlib.util
from datetime import datetime
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import patch


class Doc(dict):
    def __getattr__(self,key): return self.get(key)
    def __setattr__(self,key,value): self[key]=value
    def is_new(self): return self.get('_previous') is None
    def get_doc_before_save(self): return self.get('_previous')


class ProvenanceTests(unittest.TestCase):
    def setUp(self):
        f=types.ModuleType('frappe');f._=lambda s:s
        f.ValidationError=ValueError;f.PermissionError=PermissionError
        f.throw=lambda msg,kind=ValueError: (_ for _ in ()).throw(kind(msg))
        f.session=types.SimpleNamespace(user='staff@example.test')
        self.f=f
        utils=types.ModuleType('frappe.utils')
        utils.get_datetime=lambda v:datetime.fromisoformat(v) if isinstance(v,str) else v
        utils.now_datetime=lambda:datetime(2026,1,1,12)
        authority=types.ModuleType('lms.lms.staff_authority')
        self.calls=[]
        authority.require_capability=lambda *a,**kw:self.calls.append((a,kw))
        self.auth=authority
        self.modules=patch.dict(sys.modules,{'frappe':f,'frappe.utils':utils,'lms.lms.staff_authority':authority})
        self.modules.start()
        spec=importlib.util.spec_from_file_location('provenance_subject',Path(__file__).with_name('access_provenance.py'))
        self.m=importlib.util.module_from_spec(spec);spec.loader.exec_module(self.m)

    def tearDown(self):self.modules.stop()

    def test_old_unknown_source_is_not_invented_from_owner_or_creation(self):
        d=Doc(owner='learner@example.test',creation='2024-01-01')
        self.m.validate(d)
        self.assertEqual(d.access_source,'Unknown');self.assertIsNone(d.issued_by)

    def test_new_manual_issuer_and_time_come_from_server(self):
        d=Doc(course='c',access_source='Manual',issued_by='forged',issued_at='2000-01-01')
        self.m.validate(d)
        self.assertEqual(d.issued_by,'staff@example.test');self.assertEqual(d.issued_at,datetime(2026,1,1,12))
        self.assertEqual(self.calls,[(('course_access','create'),{'course':'c'})])

    def test_missing_create_permission_prevents_recording_manual_issuance(self):
        self.auth.require_capability=lambda *a,**kw:(_ for _ in ()).throw(PermissionError())
        with self.assertRaises(PermissionError):self.m.validate(Doc(course='c',access_source='Manual'))

    def test_staff_cannot_forge_purchase_or_import(self):
        for kind in ('Purchase','Import'):
            with self.assertRaises(PermissionError):self.m.validate(Doc(course='c',access_source=kind))

    def test_existing_issuance_cannot_be_relabelled(self):
        previous=Doc(access_source='Manual',issued_by='a',issued_at='2025-01-01')
        changed=Doc(previous,access_source='Purchase',_previous=previous)
        with self.assertRaises(ValueError):self.m.validate(changed)

    def test_datetime_readback_types_do_not_change_original_event(self):
        previous=Doc(access_source='Manual',issued_by='a',issued_at='2025-01-01 00:00:00')
        current=Doc(previous,issued_at=datetime(2025,1,1),_previous=previous)
        self.m.validate(current)

    def test_unknown_event_cannot_contain_invented_actor(self):
        with self.assertRaises(ValueError):self.m.validate(Doc(access_source='Unknown',issued_by='a'))


if __name__=='__main__':unittest.main()

"""Transaction/recovery boundaries; no real accounts or source secrets."""
from contextlib import redirect_stdout
import io
import json
import sys
from types import SimpleNamespace,ModuleType
import unittest
from unittest.mock import patch

import apply_mvcentr_contact_archive as worker
from mvcentr_contact_plan import plan
from test_mvcentr_contact_plan import row


class Doc(dict):
    def __getattr__(self,key):return self[key]


class DB:
    def __init__(self,doc):self.events=[];self.doc=doc;self.missing_support=False;self.bad_optout=False
    def begin(self):self.events.append('begin')
    def commit(self):self.events.append('commit')
    def rollback(self):self.events.append('rollback')
    def set_value(self,doctype,name,field,value,**kwargs):self.doc[field]=value;self.events.append('set_'+field)
    def sql(self,query,params=()):
        if '__Auth' in query:return [] if self.missing_support else [(1,)]
        return [(1,)] if self.bad_optout else []


class ApplicationTests(unittest.TestCase):
    def setup_user(self,**changes):
        decision=plan(row(**changes),email_frequency=1)
        doc=Doc(decision['data'],name=decision['data']['email'],enabled=1)
        db=DB(doc)
        fake=SimpleNamespace(db=db,get_doc=lambda *args:doc)
        module=ModuleType('lms.lms.avo_user_import')
        received=[]
        module.import_user=lambda data:received.append(data.copy())
        return decision,doc,db,fake,module,received

    def test_new_password_uses_existing_importer_and_disabled_source_is_not_opened(self):
        decision,doc,db,fake,module,received=self.setup_user(ban='1')
        with patch.dict(sys.modules,{'lms.lms.avo_user_import':module}):result=worker.insert_one(fake,decision)
        self.assertEqual(received,[decision['data']])
        self.assertEqual(result['kind'],'User')
        self.assertEqual(doc.enabled,0)
        self.assertEqual(db.events,['begin','set_enabled','commit'])
        self.assertNotIn('roles',received[0])

    def test_readback_identity_mismatch_rolls_back_creation(self):
        decision,doc,db,fake,module,received=self.setup_user()
        doc['custom_avo_contact_id']='456'
        with patch.dict(sys.modules,{'lms.lms.avo_user_import':module}),self.assertRaises(worker.ApplyError):
            worker.insert_one(fake,decision)
        self.assertEqual(db.events,['begin','rollback'])

    def test_missing_verified_support_copy_rolls_back_creation(self):
        decision,doc,db,fake,module,received=self.setup_user()
        db.missing_support=True
        with patch.dict(sys.modules,{'lms.lms.avo_user_import':module}),self.assertRaises(worker.ApplyError):
            worker.insert_one(fake,decision)
        self.assertEqual(db.events,['begin','rollback'])

    def test_optouts_use_monotone_existing_api_and_readback_before_commit(self):
        db=DB({});fake=SimpleNamespace(db=db)
        module=ModuleType('lms.lms.avo_marketing');calls=[]
        module.apply_source_optouts=lambda *args:calls.append(args)
        with patch.dict(sys.modules,{'lms.lms.avo_marketing':module}):worker.block_one(fake,'123')
        self.assertEqual(calls,[('mv-centr',['123'])])
        self.assertEqual(db.events,['begin','commit'])
        db.events=[];db.bad_optout=True
        with patch.dict(sys.modules,{'lms.lms.avo_marketing':module}),self.assertRaises(worker.ApplyError):worker.block_one(fake,'123')
        self.assertEqual(db.events,['begin','rollback'])

    def test_unexpected_exception_output_omits_email_and_password(self):
        module=ModuleType('frappe');module.init=lambda **kwargs:None;module.connect=lambda:None
        module.set_user=lambda _:None;module.destroy=lambda:None
        secret='SYNTHETIC_PRIVATE_EMAIL_AND_PASSWORD'
        with patch.dict(sys.modules,{'frappe':module}),patch.object(sys,'argv',['worker','--apply']), \
                patch.object(worker,'run',side_effect=RuntimeError(secret)),patch.object(worker.BASE.__class__,'is_file',return_value=False), \
                redirect_stdout(io.StringIO()) as output:
            self.assertEqual(worker.main(),1)
        self.assertNotIn(secret,output.getvalue())
        self.assertEqual(json.loads(output.getvalue())['error_type'],'RuntimeError')


if __name__=='__main__':unittest.main()

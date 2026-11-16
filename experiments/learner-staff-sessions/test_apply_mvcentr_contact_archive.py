"""Transaction/recovery boundaries; no real accounts or source secrets."""
from contextlib import redirect_stdout,nullcontext
import io
import json
import sqlite3
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
    def test_existing_only_run_skips_unknown_identity_without_invoking_insert(self):
        state=sqlite3.connect(':memory:')
        state.execute('CREATE TABLE decisions(source_id TEXT,status TEXT)')
        fake=SimpleNamespace(local=SimpleNamespace(site=worker.SITE),session=SimpleNamespace(user='Administrator'),
            conf=SimpleNamespace(encryption_key='SYNTHETIC_ONLY'),
            db=SimpleNamespace(sql=lambda _:[]),get_site_path=lambda *args:'unused')
        queue=ModuleType('frappe.utils.background_jobs');queue.get_queue=lambda _:SimpleNamespace(count=0)
        crypto=ModuleType('cryptography.fernet');crypto.Fernet=lambda _:object()
        with patch.dict(sys.modules,{'frappe.utils.background_jobs':queue,'cryptography.fernet':crypto}), \
                patch.object(worker,'private'),patch.object(worker,'policy',return_value={'excluded_ids':set(),'protected_ids':set()}), \
                patch.object(worker,'worker_lock',return_value=nullcontext()),patch.object(worker,'state_database',return_value=state), \
                patch.object(worker,'iter_contacts',side_effect=lambda *args:iter([(1,row())])), \
                patch.object(worker,'target_map',return_value={}),patch.object(worker,'progress',return_value={'status':'completed'}), \
                patch.object(worker.BASE.__class__,'exists',return_value=False),patch.object(worker,'record') as record, \
                patch.object(worker,'insert_when_ready') as insert:
            self.assertEqual(worker.run(fake),{'status':'completed'})
        self.assertEqual(record.call_args.args[2:4],('outside_existing_cohort',))
        insert.assert_not_called()

    def test_owner_existing_only_policy_rejects_insert_before_any_database_action(self):
        db=DB({})
        with self.assertRaisesRegex(worker.ApplyError,'^new_contacts_disabled_by_owner$'):
            worker.insert_one(SimpleNamespace(db=db),{'action':'create_user','data':{}})
        self.assertEqual(db.events,[])

    def test_full_queue_waits_without_attempting_or_losing_current_record(self):
        values=iter([200,150,99]);waits=[];delays=[]
        with patch.object(worker,'insert_one',return_value={'kind':'User'}) as insert:
            result=worker.insert_when_ready(None,{'data':{}},pending=lambda:next(values),
                waiting=waits.append,stopped=lambda:False,pause=delays.append)
        self.assertEqual(result,{'kind':'User'})
        self.assertEqual(waits,[200,150]);self.assertEqual(delays,[2,2]);insert.assert_called_once()

    def test_race_queue_overload_retries_same_decision_after_rollback(self):
        QueueOverloaded=type('QueueOverloaded',(Exception,),{})
        class Clock:
            value=0
            def now(self):return self.value
            def pause(self,value):self.value+=value
        clock=Clock();decision={'data':{'custom_avo_contact_id':'123'}}
        with patch.object(worker,'insert_one',side_effect=[QueueOverloaded('PRIVATE'),{'kind':'User'}]) as insert, \
                patch.object(worker.time,'monotonic',side_effect=clock.now):
            result=worker.insert_when_ready(None,decision,pending=lambda:0,waiting=lambda _:None,
                stopped=lambda:False,pause=clock.pause)
        self.assertEqual(result,{'kind':'User'})
        self.assertEqual(insert.call_count,2)
        self.assertEqual(insert.call_args_list[0],insert.call_args_list[1])

    def test_operator_stop_during_backpressure_performs_no_write(self):
        with patch.object(worker,'insert_one') as insert,self.assertRaises(worker.Paused):
            worker.insert_when_ready(None,{},pending=lambda:300,waiting=lambda _:None,stopped=lambda:True)
        insert.assert_not_called()

    def test_queue_race_retry_limit_does_not_advance_to_another_person(self):
        QueueOverloaded=type('QueueOverloaded',(Exception,),{})
        class Clock:
            value=0
            def now(self):return self.value
            def pause(self,value):
                if value<0:raise AssertionError('negative_retry_delay')
                self.value+=value
        clock=Clock();decision={'data':{'custom_avo_contact_id':'123'}}
        with patch.object(worker,'insert_one',side_effect=QueueOverloaded()) as insert, \
                patch.object(worker.time,'monotonic',side_effect=clock.now),self.assertRaises(worker.ApplyError) as error:
            worker.insert_when_ready(None,decision,pending=lambda:0,waiting=lambda _:None,
                stopped=lambda:False,pause=clock.pause)
        self.assertEqual(str(error.exception),'queue_retry_limit')
        self.assertEqual(insert.call_count,10)
        self.assertTrue(all(call.args==(None,decision) for call in insert.call_args_list))

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
        with patch.object(worker,'EXISTING_ONLY',False),patch.dict(sys.modules,{'lms.lms.avo_user_import':module}):result=worker.insert_one(fake,decision)
        self.assertEqual(received,[decision['data']])
        self.assertEqual(result['kind'],'User')
        self.assertEqual(doc.enabled,0)
        self.assertEqual(db.events,['begin','set_enabled','commit'])
        self.assertNotIn('roles',received[0])

    def test_readback_identity_mismatch_rolls_back_creation(self):
        decision,doc,db,fake,module,received=self.setup_user()
        doc['custom_avo_contact_id']='456'
        with patch.object(worker,'EXISTING_ONLY',False),patch.dict(sys.modules,{'lms.lms.avo_user_import':module}),self.assertRaises(worker.ApplyError):
            worker.insert_one(fake,decision)
        self.assertEqual(db.events,['begin','rollback'])

    def test_missing_verified_support_copy_rolls_back_creation(self):
        decision,doc,db,fake,module,received=self.setup_user()
        db.missing_support=True
        with patch.object(worker,'EXISTING_ONLY',False),patch.dict(sys.modules,{'lms.lms.avo_user_import':module}),self.assertRaises(worker.ApplyError):
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

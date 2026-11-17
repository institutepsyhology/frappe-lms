"""Synthetic MV/IOMP transaction and queue boundaries; no real contacts."""
from pathlib import Path
from contextlib import redirect_stdout
import io
import sqlite3
import sys
from types import ModuleType,SimpleNamespace
import unittest
from unittest.mock import patch

import apply_server_contacts as worker
from mvcentr_contact_plan import plan
from test_mvcentr_contact_plan import row


class Doc(dict):
    def __init__(self,*args,**kwargs):super().__init__(*args,**kwargs);self.flags=SimpleNamespace()
    def __getattr__(self,key):return self[key]


class DB:
    def __init__(self):self.events=[];self.doc=None;self.missing_support=False;self.existing=False
    def begin(self):self.events.append('begin')
    def commit(self):self.events.append('commit')
    def rollback(self):self.events.append('rollback')
    def exists(self,*args):return self.existing
    def set_value(self,kind,name,field,value,**kwargs):self.doc[field]=value
    def sql(self,sql,args=()):return [] if self.missing_support else [(1,)]


class WorkerTests(unittest.TestCase):
    def test_background_resume_propagates_retry_of_previous_deferred_records(self):
        with patch.object(sys,'argv',['worker','--account','mastervision','--start','--retry-issues']), \
                patch.object(worker,'verify_release'),patch.object(worker,'launch',return_value={'status':'starting'}) as launch, \
                redirect_stdout(io.StringIO()):
            self.assertEqual(worker.main(),0)
        launch.assert_called_once_with('mastervision',retry_issues=True,selection=None)

    def setup_user(self,account='mastervision',**changes):
        decision=plan(row(**changes),email_frequency=1,account=account)
        db=DB()
        def get_doc(*args):
            if isinstance(args[0],dict):
                db.doc=Doc(args[0],name=args[0]['email'],enabled=1)
            return db.doc
        fake=SimpleNamespace(local=SimpleNamespace(site=worker.destination(account)),session=SimpleNamespace(user='Administrator'),db=db,get_doc=get_doc)
        importer=ModuleType('lms.lms.avo_user_import');calls=[]
        importer._insert_imported_user=lambda doc:calls.append(('native_insert',doc.flags.ignore_password_policy,doc['send_welcome_email'],doc['user_type']))
        support=ModuleType('lms.lms.support_credentials');support.store_new_user_password=lambda name,password:calls.append(('support',password))
        modules={'lms.lms.avo_user_import':importer,'lms.lms.support_credentials':support}
        return decision,db,fake,modules,calls

    def test_mvc_and_unrecognized_targets_are_rejected(self):
        for account in ('mv-centr','unknown',None,{'account':'iomp'}):
            with self.assertRaisesRegex(worker.ApplyError,'^wrong_account$'):worker.destination(account)
        self.assertEqual(worker.destination('iomp'),'my-lk.iomp.ru')

    def test_wrong_site_or_payload_account_never_begins_transaction(self):
        decision,db,fake,modules,calls=self.setup_user()
        fake.local.site='my-lk.mv-centr.ru'
        with self.assertRaises(worker.ApplyError):worker.insert_one(fake,decision,'mastervision')
        self.assertEqual(db.events,[])
        fake.local.site=worker.destination('mastervision');decision['data']['custom_avo_account']='iomp'
        with self.assertRaises(worker.ApplyError):worker.insert_one(fake,decision,'mastervision')
        self.assertEqual(db.events,[])

    def test_native_insert_literal_password_support_and_source_ban(self):
        for account in ('mastervision','iomp'):
            decision,db,fake,modules,calls=self.setup_user(account,password='  SYNTHETIC_SECRET  ',ban='1')
            with patch.dict(sys.modules,modules):result=worker.insert_one(fake,decision,account)
            self.assertEqual(calls,[('native_insert',True,0,'Website User'),('support','  SYNTHETIC_SECRET  ')])
            self.assertEqual(result['kind'],'User');self.assertEqual(db.doc['enabled'],0)
            self.assertEqual(db.events,['begin','commit'])
            self.assertNotIn('roles',db.doc)

    def test_existing_identity_is_not_overwritten(self):
        decision,db,fake,modules,calls=self.setup_user();db.existing=True
        with patch.dict(sys.modules,modules),self.assertRaises(worker.ApplyError):worker.insert_one(fake,decision,'mastervision')
        self.assertEqual(db.events,['begin','rollback']);self.assertEqual(calls,[])

    def test_missing_support_copy_rolls_back_whole_new_user(self):
        decision,db,fake,modules,calls=self.setup_user();db.missing_support=True
        with patch.dict(sys.modules,modules),self.assertRaisesRegex(worker.ApplyError,'^support_copy_missing$'):
            worker.insert_one(fake,decision,'mastervision')
        self.assertEqual(db.events,['begin','rollback'])

    def test_readback_wrong_identity_rolls_back(self):
        decision,db,fake,modules,calls=self.setup_user()
        original=modules['lms.lms.avo_user_import']._insert_imported_user
        def altered(doc):original(doc);doc['custom_avo_contact_id']='999'
        modules['lms.lms.avo_user_import']._insert_imported_user=altered
        with patch.dict(sys.modules,modules),self.assertRaisesRegex(worker.ApplyError,'^contact_readback_mismatch$'):
            worker.insert_one(fake,decision,'mastervision')
        self.assertEqual(db.events,['begin','rollback'])

    def test_native_queue_overload_rolls_back_before_retry(self):
        decision,db,fake,modules,calls=self.setup_user()
        QueueOverloaded=type('QueueOverloaded',(Exception,),{})
        def overload(doc):raise QueueOverloaded('SYNTHETIC_PRIVATE')
        modules['lms.lms.avo_user_import']._insert_imported_user=overload
        with patch.dict(sys.modules,modules),self.assertRaises(QueueOverloaded):worker.insert_one(fake,decision,'mastervision')
        self.assertEqual(db.events,['begin','rollback'])

    def test_no_email_contact_has_no_fabricated_email_and_no_user_link(self):
        decision=plan(row(email='',name='',last_name='',phone_number=''),account='iomp')
        db=DB();received=[]
        saved=Doc(decision['data'],name='avo-iomp-contact-123')
        def insert(**kwargs):received.append(kwargs)
        saved.insert=insert
        fake=SimpleNamespace(local=SimpleNamespace(site=worker.destination('iomp')),session=SimpleNamespace(user='Administrator'),db=db,get_doc=lambda *args:saved)
        result=worker.insert_one(fake,decision,'iomp')
        self.assertEqual(result['kind'],'Contact');self.assertEqual(db.events,['begin','commit'])
        self.assertTrue(received[0]['ignore_mandatory']);self.assertNotIn('email_ids',saved)
        self.assertNotIn('user',saved)

    def test_shared_email_requires_durable_guard_and_preserves_separate_source_id(self):
        decision=plan(row(),account='mastervision',email_frequency=2)
        db=DB();received=[]
        module=ModuleType('lms.lms.avo_contact_binding')
        class Mixin:pass
        module.AvoContactIdentityMixin=Mixin
        class BoundContact(Doc,Mixin):pass
        saved=BoundContact(decision['data'],name='avo-mastervision-contact-123',email_id='person@example.invalid',mobile_no='999999999')
        saved.insert=lambda **kwargs:received.append(kwargs)
        fake=SimpleNamespace(local=SimpleNamespace(site=worker.destination('mastervision')),session=SimpleNamespace(user='Administrator'),db=db,get_doc=lambda *args:saved)
        with patch.dict(sys.modules,{'lms.lms.avo_contact_binding':module}):
            result=worker.insert_one(fake,decision,'mastervision')
        self.assertEqual(result['kind'],'Contact');self.assertEqual(db.events,['begin','commit'])
        self.assertEqual(received[0]['set_name'],'avo-mastervision-contact-123')
        self.assertEqual(saved['email_ids'][0]['email_id'],'person@example.invalid')
        self.assertNotIn('user',saved)
        db.events=[];fake.get_doc=lambda *args:Doc(decision['data'])
        with patch.dict(sys.modules,{'lms.lms.avo_contact_binding':module}),self.assertRaisesRegex(worker.ApplyError,'^source_identity_guard_not_installed$'):
            worker.insert_one(fake,decision,'mastervision')
        self.assertEqual(db.events,['begin','rollback'])

    def test_waits_for_free_disk_then_queue_then_inserts_current_record(self):
        free=iter([0,worker.RESERVE,worker.RESERVE]);pending=iter([100,99]);waits=[];delays=[]
        with patch.object(worker,'insert_one',return_value={'kind':'User'}) as insert:
            result=worker.insert_ready(None,{'data':{}},'mastervision',free=lambda:next(free),pending=lambda:next(pending),
                stopped=lambda:False,waiting=waits.append,pause=delays.append)
        self.assertEqual(result,{'kind':'User'});self.assertEqual(waits,['waiting_for_space','waiting_for_queue'])
        self.assertEqual(delays,[2,1]);insert.assert_called_once()

    def test_stop_while_waiting_does_not_insert(self):
        with patch.object(worker,'insert_one') as insert,self.assertRaises(worker.Paused):
            worker.insert_ready(None,{},'iomp',pending=lambda:999,free=lambda:worker.RESERVE,stopped=lambda:True,waiting=lambda _:None)
        insert.assert_not_called()

    def test_queue_race_retries_exact_same_record_and_limit_stops(self):
        QueueOverloaded=type('QueueOverloaded',(Exception,),{})
        decision={'data':{'source_id':'123'}}
        with patch.object(worker,'insert_one',side_effect=QueueOverloaded()) as insert,self.assertRaisesRegex(worker.ApplyError,'^queue_retry_limit$'):
            worker.insert_ready(None,decision,'iomp',pending=lambda:0,free=lambda:worker.RESERVE,
                stopped=lambda:False,waiting=lambda _:None,pause=lambda _:None)
        self.assertEqual(insert.call_count,10)
        self.assertTrue(all(call.args==(None,decision,'iomp') for call in insert.call_args_list))

    def test_positive_optout_is_scoped_and_committed(self):
        db=DB();db.missing_support=True;fake=SimpleNamespace(db=db)
        module=ModuleType('lms.lms.avo_marketing');calls=[];module.apply_source_optouts=lambda *args:calls.append(args)
        with patch.dict(sys.modules,{'lms.lms.avo_marketing':module}):worker.apply_optout(fake,'mastervision','123')
        self.assertEqual(calls,[('mastervision',['123'])]);self.assertEqual(db.events,['begin','commit'])


if __name__=='__main__':unittest.main()

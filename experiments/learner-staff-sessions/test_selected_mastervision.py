"""Synthetic scope and encryption checks; no real data or network."""
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
from types import ModuleType,SimpleNamespace
import unittest
from unittest.mock import patch
import zlib

from cryptography.fernet import Fernet
import apply_server_contacts as worker
import selected_mastervision_links as links
import manage_selected_mastervision as control
from test_mvcentr_contact_plan import row


def selection(ids=(123,125)):
    return {'ids':list(ids),'manifest':{'format':'mastervision-contact-selection-v1',
        'account':'mastervision','union_count':len(ids),
        'fingerprint':hashlib.sha256(''.join(str(i)+'\n' for i in ids).encode()).hexdigest()}}


class ServerPlatformTest(unittest.TestCase):
    def setUp(self):
        # Production runs on Linux. Windows synthetic tests retain all explicit
        # safe_file checks and emulate only unavailable Linux syscall constants.
        for name,value in (('O_NOFOLLOW',getattr(os,'O_NOFOLLOW',0)),('getuid',getattr(os,'getuid',lambda:0))):
            patcher=patch.object(os,name,value,create=True);patcher.start();self.addCleanup(patcher.stop)


class SelectionTests(ServerPlatformTest):
    def test_exact_scope_and_digest(self):
        value=selection();actual,digest=worker.validate_selection(value)
        self.assertEqual(actual,{'123','125'});self.assertEqual(digest,value['manifest']['fingerprint'])

    def test_invalid_scope_never_accepted(self):
        cases=[selection(()),selection((123,123)),selection((125,123)),selection((True,)),selection((0,)),selection((2**63,))]
        bad=selection();bad['manifest']['account']='iomp';cases.append(bad)
        bad=selection();bad['manifest']['fingerprint']='0'*64;cases.append(bad)
        for value in cases:
            with self.subTest(value=value),self.assertRaises(worker.ApplyError):worker.validate_selection(value)

    def test_scope_rejects_other_account_before_file_read(self):
        with self.assertRaisesRegex(worker.ApplyError,'^wrong_account$'):worker.read_selection('iomp','a'*64)
        with self.assertRaises(worker.ApplyError):worker.selection_path('../outside')

    def test_selected_run_never_inserts_unselected_source(self):
        self.run_selection([row(id_contact='123'),row(id_contact='124'),row(id_contact='125')],False)

    def test_missing_source_id_prevents_all_writes(self):
        self.run_selection([row(id_contact='123'),row(id_contact='124')],True)

    def test_resume_replays_fresh_optout_after_native_commit_or_done_ledger(self):
        self.run_selection([row(id_contact='123'),row(id_contact='124'),row(id_contact='125')],False,replay=True)

    def run_selection(self,rows,missing,*,replay=False):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);job=root/'avo-api-archive/job-20261116';job.mkdir(parents=True)
            general=root/'apply-avo-contacts';general.mkdir();(general/'STOP').write_text('OWNER PAUSE')
            folder=root/'selected';folder.mkdir()
            if replay:
                application=folder/'application';application.mkdir()
                with closing(worker.open_state(application,'mastervision','synthetic:'+('a'*64))) as state:
                    worker.record(state,'123','created_user')
            with closing(sqlite3.connect(job/'snapshot.sqlite')) as db,db:
                db.execute('CREATE TABLE metadata(key TEXT,value TEXT)');db.execute("INSERT INTO metadata VALUES ('snapshot','synthetic')")
            fake=SimpleNamespace(local=SimpleNamespace(site=worker.SITES['mastervision']),session=SimpleNamespace(user='Administrator'),
                conf=SimpleNamespace(encryption_key=Fernet.generate_key().decode()),
                get_site_path=lambda *parts:str(root.joinpath(*parts[1:])),db=SimpleNamespace(sql=lambda _:[]))
            reader=ModuleType('server_contact_reader');reader.iter_contacts=lambda *args:iter(rows)
            jobs=ModuleType('frappe.utils.background_jobs');jobs.get_queue=lambda _:SimpleNamespace(count=0)
            result_map={'123':{'kind':'User'},'125':{'kind':'User'}}
            initial={'123':{'kind':'User','blocked':False}} if replay else {}
            with patch.dict(sys.modules,{'server_contact_reader':reader,'frappe.utils.background_jobs':jobs}), \
                    patch.object(worker,'read_selection',return_value=({'123','125'},folder)), \
                    patch.object(worker,'lock') as lock,patch.object(worker,'target_map',side_effect=[initial,result_map]), \
                    patch.object(worker,'fresh_optout',side_effect=lambda folder,ident:replay and ident=='123'), \
                    patch.object(worker.shutil,'disk_usage',return_value=SimpleNamespace(free=worker.RESERVE)), \
                    patch.object(worker,'apply_optout') as apply_optout, \
                    patch.object(worker,'insert_ready',return_value={'kind':'User'}) as insert,patch.object(worker.time,'sleep'):
                if missing:
                    with self.assertRaisesRegex(worker.ApplyError,'^selection_missing_source$'):
                        worker.run(fake,'mastervision',selection='a'*64,limit=0)
                    insert.assert_not_called()
                else:
                    report=worker.run(fake,'mastervision',selection='a'*64,limit=0)
                    self.assertEqual(report['status'],'completed')
                    self.assertEqual({call.args[1]['data']['custom_avo_contact_id'] for call in insert.call_args_list},
                        {'125'} if replay else {'123','125'})
                    if replay:apply_optout.assert_called_once_with(fake,'mastervision','123')
                self.assertEqual((general/'STOP').read_text(),'OWNER PAUSE')
                lock.assert_called_once_with(general)


class ProfileTests(ServerPlatformTest):
    def test_profile_saved_encrypted_bound_and_repeat_updates(self):
        cipher=Fernet(Fernet.generate_key());detail={'id_contact':'123','password':'SYNTHETIC_PASSWORD','name':'Test'}
        with tempfile.TemporaryDirectory() as directory,closing(links.open_profiles(Path(directory),'a'*64)) as db:
            calls=[]
            for _ in range(2):links.save_profile(db,cipher,'a'*64,123,detail,'SYNTHETIC_API_KEY',lambda raw,key:calls.append((raw,key)))
            rows=list(db.execute('SELECT source_id,sha256,encrypted FROM profiles'))
            self.assertEqual(len(rows),1);self.assertNotIn(b'SYNTHETIC_PASSWORD',rows[0][2])
            saved=json.loads(zlib.decompress(cipher.decrypt(rows[0][2])))
            self.assertEqual(saved['profile'],detail);self.assertEqual(saved['source_id'],123)
            self.assertEqual(saved['site'],'my-lk.mastervision.su');self.assertEqual(saved['selection'],'a'*64)
            self.assertEqual(len(calls),2)

    def test_wrong_identity_and_key_leak_prevent_persistence(self):
        cipher=Fernet(Fernet.generate_key())
        with tempfile.TemporaryDirectory() as directory,closing(links.open_profiles(Path(directory),'a'*64)) as db:
            with self.assertRaises(worker.ApplyError):links.save_profile(db,cipher,'a'*64,123,{'id_contact':'124'},'key',lambda *_:None)
            def reject(*_):raise ValueError('fixed_error')
            with self.assertRaises(ValueError):links.save_profile(db,cipher,'a'*64,123,{'id_contact':'123'},'key',reject)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM profiles').fetchone()[0],0)

    def test_profile_database_cannot_be_resumed_for_different_selection(self):
        with tempfile.TemporaryDirectory() as directory:
            links.open_profiles(Path(directory),'a'*64).close()
            with self.assertRaises(worker.ApplyError):links.open_profiles(Path(directory),'b'*64)

    def test_fresh_optout_survives_older_profile_and_is_selection_bound(self):
        cipher=Fernet(Fernet.generate_key());detail={'id_contact':'123'}
        with tempfile.TemporaryDirectory() as directory:
            folder=Path(directory)/('a'*64);folder.mkdir();output=folder/'individual';output.mkdir()
            with closing(links.open_profiles(output,'a'*64)) as db:
                links.save_profile(db,cipher,'a'*64,123,detail,'key',lambda *_:None,optout=True)
                links.save_profile(db,cipher,'a'*64,123,detail,'key',lambda *_:None,optout=False)
            self.assertTrue(worker.fresh_optout(folder,'123'))
            self.assertFalse(worker.fresh_optout(folder,'125'))
            other=Path(directory)/('b'*64);other.mkdir();(folder/'individual').rename(other/'individual')
            with self.assertRaises(worker.ApplyError):worker.fresh_optout(other,'123')

    def test_key_only_in_stdin_not_argv(self):
        completed=SimpleNamespace(returncode=0,stdout=json.dumps({'status':'starting','account':'mastervision',
            'site':'my-lk.mastervision.su','worker_pid':123,'key_saved':False}).encode())
        with patch.object(control.subprocess,'run',return_value=completed) as run:
            control.start_links('a'*40,'b'*64,'SYNTHETIC_API_KEY')
        self.assertNotIn('SYNTHETIC_API_KEY',str(run.call_args.args[0]))
        self.assertIn(b'SYNTHETIC_API_KEY',run.call_args.kwargs['input'])
        self.assertNotIn('env',run.call_args.kwargs)


if __name__=='__main__':unittest.main()

"""Synthetic manifest/SSH/index checks; no actual transport or source archive."""
import copy
import ctypes
import errno
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
import uuid

import audio_stage_client as client
from importer import Stop

URL = 'https://f1.autoweboffice.ru/synthetic/audio.mp3'
REAL_REMOTE = client._remote


def payload(url=URL):
    return {'account':'mastervision','source_origin':client.ORIGIN,'course_id':297,'lesson_id':1992,
            'format':'ape','ape':{'name':'page','children':[{'name':'audio','id':'audio-1','children':[],
            'fields':{'anchor':'','audioSrc':url,'showDownloadButton':False,'showLoopButton':True,
                      'showStopButton':True,'showVolumeButton':True,'showVolumeSlider':True}}]}}


def inventory(source):
    files = []
    for i, node in enumerate(source['ape']['children']):
        url = node['fields']['audioSrc']
        files.append({'url_sha256':hashlib.sha256(url.encode()).hexdigest(),'size_bytes':100,
                      'mime':'audio/mpeg','http_status':200,'reachable':True,'error':None,
                      'references':[{'course_id':297,'lesson_id':1992,'block_path':[i]}]})
    return {'version':1,'account':'mastervision','origin':client.ORIGIN,'files':files}


def receipt(url=URL, size=100, code='audio_staged'):
    key = hashlib.sha256(url.encode()).hexdigest()
    return {'code':code,'basename':client.PREFIX+key+'.mp3','url_sha256':key,'size':size,
            'sha256':'a'*64,'md5':'b'*32}


class Store:
    def __init__(self, directory): self.directory, self.payload, self.reads = directory, payload(), []
    def completed_course(self, cid):
        self.reads.append(cid)
        return [copy.deepcopy(self.payload)] if cid == 297 else []


class ClientTests(unittest.TestCase):
    def setUp(self):
        self.parent = Path(__file__).resolve().parents[3]/'.tmp-mastervision-audio-client-tests'
        self.parent.mkdir(exist_ok=True)
        self.folder = self.parent/('fixture-'+uuid.uuid4().hex); self.folder.mkdir()
        self.addCleanup(self.cleanup)
        self.store, self.events = Store(self.folder), []
        self.manifest = inventory(self.store.payload); self.write_manifest()
        self.transport = patch.object(client, '_remote', side_effect=lambda url,size:receipt(url,size))
        self.remote = self.transport.start(); self.addCleanup(self.transport.stop)

    def cleanup(self):
        if self.folder.parent.resolve()!=self.parent.resolve() or not self.folder.name.startswith('fixture-'):
            raise RuntimeError('unsafe_fixture_cleanup')
        shutil.rmtree(self.folder)

    def write_manifest(self):
        (self.folder/'audio-inventory.json').write_text(json.dumps(self.manifest),encoding='utf-8')

    def run_stage(self): return client.stage_audio(self.store,self.events.append)

    def windows_probe(self, *, attributes=0x80, handle=123, error=0, info_attributes=0x80,
                      info_result=True, close_result=True):
        def information(opened, pointer):
            pointer._obj.dwFileAttributes=info_attributes
            return info_result
        api=SimpleNamespace(GetFileAttributesW=Mock(return_value=attributes),
                            CreateFileW=Mock(return_value=handle),
                            GetFileInformationByHandle=Mock(side_effect=information),
                            CloseHandle=Mock(return_value=close_result))
        path=self.folder/'probe.json'
        with patch.object(client.os,'name','nt'), \
                patch.object(ctypes,'WinDLL',return_value=api,create=True), \
                patch.object(ctypes,'get_last_error',return_value=error,create=True):
            result=client._windows_replace_state(path)
        return result,api

    def test_windows_probe_requires_positive_delete_access_and_regular_writable_handle(self):
        state,api=self.windows_probe()
        self.assertEqual(state,'delete_allowed')
        self.assertTrue(api.CreateFileW.call_args.args[1]&0x10000)
        self.assertEqual(api.CreateFileW.call_args.args[2],7)
        self.assertTrue(api.CreateFileW.call_args.args[5]&0x200000)
        api.GetFileInformationByHandle.assert_called_once();api.CloseHandle.assert_called_once_with(123)
        for attr in (1,0x10,0x400,0xffffffff):
            state,api=self.windows_probe(attributes=attr)
            self.assertEqual(state,'denied');api.CreateFileW.assert_not_called();api.CloseHandle.assert_not_called()
        for attr in (1,0x10,0x400):
            state,api=self.windows_probe(info_attributes=attr)
            self.assertEqual(state,'denied');api.CloseHandle.assert_called_once_with(123)
        for options in ({'info_result':False},{'close_result':False}):
            state,api=self.windows_probe(**options)
            self.assertEqual(state,'denied');api.CloseHandle.assert_called_once_with(123)

    def test_windows_probe_distinguishes_sharing_error_from_real_delete_denial(self):
        invalid=ctypes.c_void_p(-1).value
        for code in (32,33,5,2,112):
            state,api=self.windows_probe(handle=invalid,error=code)
            self.assertEqual(state,'sharing_busy' if code in (32,33) else 'denied')
            api.GetFileInformationByHandle.assert_not_called();api.CloseHandle.assert_not_called()

    def test_win5_after_reader_has_closed_retries_only_the_local_replace(self):
        self.run_stage();self.remote.reset_mock()
        real_replace=client.os.replace;attempts=[]
        error=PermissionError(errno.EACCES,'PRIVATE');error.winerror=5
        def rename(source,target):
            attempts.append(1)
            if len(attempts)==1:raise error
            return real_replace(source,target)
        with patch.object(client.os,'replace',side_effect=rename), \
                patch.object(client,'_windows_replace_state',return_value='delete_allowed') as probe, \
                patch.object(client.time,'sleep') as sleep:
            self.run_stage()
        self.assertEqual(len(attempts),2);self.remote.assert_called_once_with(URL,100)
        probe.assert_called_once_with(self.folder/'audio-stage-index.json');sleep.assert_called_once_with(0.02)
        self.assertEqual(list(self.folder.glob('*.tmp')),[])

    def test_unproven_win5_never_retries_local_or_remote_write(self):
        self.run_stage();self.remote.reset_mock()
        error=PermissionError(errno.EACCES,'PRIVATE');error.winerror=5
        with patch.object(client.os,'replace',side_effect=error) as rename, \
                patch.object(client,'_windows_replace_state',return_value='denied'), \
                patch.object(client.time,'sleep') as sleep:
            with self.assertRaisesRegex(Stop,'^audio_stage_index_access_denied$'):self.run_stage()
        rename.assert_called_once();sleep.assert_not_called();self.remote.assert_called_once_with(URL,100)

    @unittest.skipUnless(os.name=='nt','Windows close-before-probe regression')
    def test_real_windows_reader_closing_between_rename_error_and_probe_is_retryable(self):
        path=self.folder/'index.json';path.write_text('{"old":true}');reader=path.open('rb')
        real_replace=os.replace;errors=[]
        def rename(source,target):
            try:return real_replace(source,target)
            except OSError as exc:
                errors.append(getattr(exc,'winerror',None));reader.close()
                # Exercise WinError5 even on Windows variants reporting32/33.
                error=PermissionError(errno.EACCES,'synthetic sharing collision');error.winerror=5
                raise error from None
        try:
            self.assertTrue(client._windows_reader_blocks_replace(path))
            with patch.object(client.os,'replace',side_effect=rename) as replace:
                client._save_index(path,{'new':True})
            self.assertEqual(replace.call_count,2)
            self.assertEqual(client._windows_replace_state(path),'delete_allowed')
        finally:reader.close()
        self.assertIn(errors[0],(5,32,33));self.assertEqual(json.loads(path.read_text()),{'new':True})
        self.assertEqual(list(self.folder.glob('*.tmp')),[])

    def test_only_completed_source_reads_remote_staging_and_metadata_index(self):
        before = copy.deepcopy(self.store.payload); result = self.run_stage()
        self.assertEqual(self.store.reads,list(client.COURSES)); self.assertEqual(self.store.payload,before)
        self.assertEqual(result,{'stage':'audio','completed':1,'total':1,'size':100})
        self.remote.assert_called_once_with(URL,100)
        index=json.loads((self.folder/'audio-stage-index.json').read_text())
        self.assertEqual((index['account'],index['origin'],index['site']),('mastervision',client.ORIGIN,client.SITE))
        self.assertEqual(set(next(iter(index['files'].values()))),client.FIELDS)
        self.assertNotIn(URL,json.dumps(index)); self.assertNotIn(URL,json.dumps(self.events))
        self.assertEqual(self.events[0],{'stage':'audio','completed':0,'total':1})

    def test_resume_always_revalidates_remote_then_reuses_without_changing_receipt(self):
        self.run_stage(); path=self.folder/'audio-stage-index.json'; original=path.read_bytes()
        self.remote.side_effect=lambda url,size:receipt(url,size,'audio_reused')
        self.events.clear(); self.run_stage()
        self.assertEqual(self.remote.call_count,2); self.assertEqual(path.read_bytes(),original)
        self.assertEqual(self.events[-1]['code'],'audio_reused')

    def test_inventory_account_origin_sha_size_and_reference_mismatches_preflight_before_ssh(self):
        changes=[('account','mv-centr'),('origin','https://shop.mv-centr.ru'),('version',2)]
        for key,value in changes:
            original=copy.deepcopy(self.manifest); self.manifest[key]=value; self.write_manifest()
            with self.subTest(key=key),self.assertRaises(Stop):self.run_stage()
            self.manifest=original
        for key,value in [('url_sha256','c'*64),('size_bytes',True),('mime','text/html'),
                          ('reachable',False),('references',[{'course_id':297,'lesson_id':1993,'block_path':[0]}])]:
            original=copy.deepcopy(self.manifest); self.manifest['files'][0][key]=value; self.write_manifest()
            with self.subTest(key=key),self.assertRaises(Stop):self.run_stage()
            self.manifest=original
        self.assertEqual(self.remote.call_count,0); self.assertEqual(list(self.folder.iterdir()),[self.folder/'audio-inventory.json'])

    def test_entire_source_is_checked_before_staging_unknown_audio_or_cross_account(self):
        mutations=[('account','mv-centr'),('source_origin','https://shop.iomp.ru'),('course_id',324)]
        for key,value in mutations:
            old=copy.deepcopy(self.store.payload);self.store.payload[key]=value
            with self.assertRaises(Stop):self.run_stage()
            self.store.payload=old
        audio=self.store.payload['ape']['children'][0]
        for key,value in [('unknown',None),('anchor','keep-anchor'),('showLoopButton','yes'),
                          ('audioSrc',URL+'?redirect=private')]:
            old=copy.deepcopy(audio['fields']);audio['fields'][key]=value
            with self.subTest(key=key),self.assertRaises(Stop):self.run_stage()
            audio['fields']=old
        audio['children']=[{'name':'text','fields':{'html':'Keep'}}]
        with self.assertRaisesRegex(Stop,'audio_source_unsupported'):self.run_stage()
        self.assertEqual(self.remote.call_count,0)

    def test_duplicate_inventory_rows_or_refs_never_stage(self):
        self.manifest['files'].append(copy.deepcopy(self.manifest['files'][0]));self.write_manifest()
        with self.assertRaises(Stop):self.run_stage()
        self.manifest=inventory(self.store.payload)
        self.manifest['files'][0]['references']*=2;self.write_manifest()
        with self.assertRaises(Stop):self.run_stage()
        self.assertEqual(self.remote.call_count,0)

    def test_uncertain_remote_write_stops_immediately_without_index_or_next_file(self):
        second=copy.deepcopy(self.store.payload['ape']['children'][0]);second['fields']['audioSrc']=URL.replace('audio','second')
        self.store.payload['ape']['children'].append(second);self.manifest=inventory(self.store.payload);self.write_manifest()
        self.remote.side_effect=Stop('audio_remote_result_uncertain')
        with self.assertRaisesRegex(Stop,'^audio_remote_result_uncertain$'):self.run_stage()
        self.assertEqual(self.remote.call_count,1);self.assertFalse((self.folder/'audio-stage-index.json').exists())

    def test_invalid_or_changed_receipt_cannot_replace_verified_index(self):
        self.run_stage();path=self.folder/'audio-stage-index.json';original=path.read_bytes()
        wrong=receipt();wrong['sha256']='c'*64;self.remote.side_effect=None;self.remote.return_value=wrong
        with self.assertRaisesRegex(Stop,'audio_stage_receipt_changed'):self.run_stage()
        self.assertEqual(path.read_bytes(),original)
        for key,value in [('size',101),('url_sha256','d'*64),('basename','other.mp3'),('sha256','bad')]:
            wrong=receipt();wrong[key]=value;self.remote.return_value=wrong
            with self.subTest(key=key),self.assertRaises(Stop):self.run_stage()
            self.assertEqual(path.read_bytes(),original)

    def test_wrong_account_index_and_atomic_write_failure_do_not_lose_existing_index(self):
        self.run_stage();path=self.folder/'audio-stage-index.json';original=path.read_bytes()
        bad=json.loads(original);bad['account']='mv-centr';path.write_text(json.dumps(bad));self.remote.reset_mock()
        with self.assertRaisesRegex(Stop,'audio_stage_index_invalid'):self.run_stage()
        self.remote.assert_not_called();path.write_bytes(original)
        with patch.object(client.os,'replace',side_effect=OSError('synthetic private details')):
            with self.assertRaisesRegex(Stop,'audio_stage_index_write_failed'):self.run_stage()
        self.assertEqual(path.read_bytes(),original);self.assertEqual(list(self.folder.glob('*.tmp')),[])

    @unittest.skipUnless(os.name=='nt','Windows read-sharing regression')
    def test_real_windows_read_handle_blocks_replace_then_retry_succeeds_after_close(self):
        path=self.folder/'index.json';path.write_text('{"old":true}');reader=path.open('rb')
        real_replace=os.replace;timers=[];errors=[];started=time.monotonic()
        def replace(source,target):
            try:return real_replace(source,target)
            except OSError as exc:
                errors.append(getattr(exc,'winerror',None))
                if not timers:
                    timer=threading.Timer(0.06,reader.close);timers.append(timer);timer.start()
                raise
        try:
            self.assertTrue(client._windows_reader_blocks_replace(path))
            with patch.object(client.os,'replace',side_effect=replace) as rename:
                client._save_index(path,{'new':True})
            self.assertGreaterEqual(rename.call_count,2)
        finally:
            reader.close()
            for timer in timers:timer.join(timeout=1)
        self.assertIn(errors[0],(5,32,33));self.assertEqual(json.loads(path.read_text()),{'new':True})
        self.assertLess(time.monotonic()-started,1.0);self.assertEqual(list(self.folder.glob('*.tmp')),[])

    @unittest.skipUnless(os.name=='nt','Windows genuine access-denied regression')
    def test_real_readonly_target_access_denied_is_not_retried(self):
        path=self.folder/'index.json';original=b'{"old":true}';path.write_bytes(original);os.chmod(path,stat.S_IREAD)
        real_replace=os.replace
        try:
            self.assertFalse(client._windows_reader_blocks_replace(path))
            with patch.object(client.os,'replace',wraps=real_replace) as rename,patch.object(client.time,'sleep') as sleep:
                with self.assertRaisesRegex(Stop,'^audio_stage_index_access_denied$'):client._save_index(path,{'new':True})
            self.assertEqual(rename.call_count,1);sleep.assert_not_called();self.assertEqual(path.read_bytes(),original)
        finally:os.chmod(path,stat.S_IREAD|stat.S_IWRITE)

    def test_disk_full_and_unproven_access_denied_stop_immediately_with_safe_codes(self):
        path=self.folder/'index.json';path.write_text('{"old":true}');original=path.read_bytes()
        for error,code in [(OSError(errno.ENOSPC,'PRIVATE'), 'audio_stage_index_disk_full'),
                           (PermissionError(errno.EACCES,'PRIVATE'),'audio_stage_index_access_denied')]:
            with patch.object(client.os,'replace',side_effect=error) as rename,patch.object(client.time,'sleep') as sleep:
                with self.assertRaisesRegex(Stop,'^'+code+'$') as raised:client._save_index(path,{'new':True})
            self.assertNotIn('PRIVATE',str(raised.exception));self.assertEqual(rename.call_count,1);sleep.assert_not_called()
            self.assertEqual(path.read_bytes(),original);self.assertEqual(list(self.folder.glob('*.tmp')),[])

    def test_permanent_windows_busy_is_bounded_and_does_not_retry_remote_staging(self):
        path=self.folder/'index.json';path.write_text('{"old":true}');original=path.read_bytes()
        error=PermissionError(errno.EACCES,'PRIVATE');error.winerror=32
        with patch.object(client.os,'replace',side_effect=error) as rename,patch.object(client.time,'sleep') as sleep:
            with self.assertRaisesRegex(Stop,'^audio_stage_index_file_busy$'):client._save_index(path,{'new':True})
        self.assertEqual(rename.call_count,8);self.assertLessEqual(sum(call.args[0] for call in sleep.call_args_list),0.8)
        self.remote.assert_not_called();self.assertEqual(path.read_bytes(),original);self.assertEqual(list(self.folder.glob('*.tmp')),[])

    def test_symlink_guard_is_rechecked_before_retry(self):
        path=self.folder/'index.json';path.write_text('{"old":true}');real_symlink=Path.is_symlink;checks=0
        error=PermissionError(errno.EACCES,'PRIVATE');error.winerror=33
        def is_symlink(selected):
            nonlocal checks
            if selected==path:
                checks+=1;return checks>=3
            return real_symlink(selected)
        with patch.object(Path,'is_symlink',is_symlink),patch.object(client.os,'replace',side_effect=error) as rename,patch.object(client.time,'sleep'):
            with self.assertRaisesRegex(Stop,'^audio_stage_index_invalid$'):client._save_index(path,{'new':True})
        self.assertEqual(rename.call_count,1);self.assertGreaterEqual(checks,3)

    def test_fsync_space_failure_is_classified_without_replacing_existing_index(self):
        path=self.folder/'index.json';path.write_text('{"old":true}');original=path.read_bytes()
        with patch.object(client.os,'fsync',side_effect=OSError(errno.ENOSPC,'PRIVATE')),patch.object(client.os,'replace') as rename:
            with self.assertRaisesRegex(Stop,'^audio_stage_index_disk_full$'):client._save_index(path,{'new':True})
        rename.assert_not_called();self.assertEqual(path.read_bytes(),original);self.assertEqual(list(self.folder.glob('*.tmp')),[])

    def test_ssh_uses_pinned_host_key_hidden_window_and_private_url_stdin_only(self):
        with patch.object(client.subprocess,'run',return_value=SimpleNamespace(returncode=0,stdout=json.dumps(receipt()).encode())) as run:
            output=REAL_REMOTE(URL,100)
        self.assertEqual(output,receipt());args=run.call_args.args[0];options=run.call_args.kwargs
        self.assertEqual(args[0],'ssh');self.assertIn('StrictHostKeyChecking=yes',args)
        self.assertTrue(any(x.startswith('UserKnownHostsFile=') and x.replace('\\','/').endswith('frappe-deploy/known_hosts') for x in args))
        self.assertIn('root@89.223.71.30',args);self.assertIn('company-lms-backend-1',args[-1])
        self.assertNotIn(URL,repr(args));self.assertEqual(json.loads(options['input'])['url'],URL)
        self.assertEqual(options['stderr'],subprocess.DEVNULL);self.assertEqual(options['timeout'],180)
        self.assertIn('creationflags',options)

    def test_ssh_failure_and_bad_response_are_sanitized_without_retry(self):
        for error in (OSError('PRIVATE_AUTH_URL'),subprocess.TimeoutExpired(['PRIVATE_AUTH_URL'],180)):
            with patch.object(client.subprocess,'run',side_effect=error) as run:
                with self.assertRaisesRegex(Stop,'^audio_remote_result_uncertain$') as raised:REAL_REMOTE(URL,100)
            run.assert_called_once();self.assertNotIn('PRIVATE',str(raised.exception))
        with patch.object(client.subprocess,'run',return_value=SimpleNamespace(returncode=1,stdout=b'{"code":"audio_redirect_forbidden"}')):
            with self.assertRaisesRegex(Stop,'^audio_redirect_forbidden$'):REAL_REMOTE(URL,100)
        with patch.object(client.subprocess,'run',return_value=SimpleNamespace(returncode=1,stdout=b'PRIVATE_AUTH_DETAILS')):
            with self.assertRaisesRegex(Stop,'^audio_remote_result_uncertain$'):REAL_REMOTE(URL,100)


if __name__=='__main__':
    unittest.main()

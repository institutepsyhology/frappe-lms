"""Synthetic manifest/SSH/index checks; no actual transport or source archive."""
import copy
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
from types import SimpleNamespace
import unittest
from unittest.mock import patch
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

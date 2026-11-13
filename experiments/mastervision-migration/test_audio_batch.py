"""Synthetic batch checkpoints; all MCP registration and settings calls mocked."""
import copy
import hashlib
import json
from pathlib import Path
import shutil
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import uuid

import audio_batch as batch
from importer import ACCOUNT,ORIGIN,SITE,Stop
from server_audio_stage import PREFIX


class Store:
    def __init__(self,directory):
        self.directory=directory;self.reads=[]
        self.payload={'account':ACCOUNT,'source_origin':ORIGIN,'course_id':297,'lesson_id':1992,'format':'ape',
            'ape':{'name':'page','children':[{'name':'audio','fields':{'audioSrc':'https://f1.autoweboffice.ru/synthetic/'+str(n)+'.mp3'}} for n in range(2)]}}
    def completed_course(self,cid):
        self.reads.append(cid);return [copy.deepcopy(self.payload)] if cid==297 else []


def mapping(row):
    return {'file_url':'/private/files/avo-mastervision-audio-'+row['sha256']+'.mp3',
            'sha256':row['sha256'],'md5':row['md5'],'size':row['size']}


class AudioBatchTests(unittest.TestCase):
    def setUp(self):
        self.parent=Path(__file__).resolve().parents[3]/'.tmp-mastervision-audio-batch-tests';self.parent.mkdir(exist_ok=True)
        self.folder=self.parent/('fixture-'+uuid.uuid4().hex);self.folder.mkdir();self.addCleanup(self.cleanup)
        self.store=Store(self.folder);self.client=SimpleNamespace(account=ACCOUNT,site=SITE);self.events=[]
        self.stage={'version':1,'account':ACCOUNT,'origin':ORIGIN,'site':SITE,'files':{}};files=[]
        for n,node in enumerate(self.store.payload['ape']['children']):
            key=hashlib.sha256(node['fields']['audioSrc'].encode()).hexdigest()
            files.append({'url_sha256':key,'size_bytes':100+n,'mime':'audio/mpeg','http_status':200,'reachable':True,
                'error':None,'references':[{'course_id':297,'lesson_id':1992,'block_path':[n]}]})
            self.stage['files'][key]={'basename':PREFIX+key+'.mp3','url_sha256':key,'size':100+n,
                                     'sha256':('a' if n==0 else 'b')*64,'md5':('c' if n==0 else 'd')*32}
        self.inventory={'version':1,'account':ACCOUNT,'origin':ORIGIN,'site':SITE,'files':files}
        self.write('audio-inventory.json',self.inventory);self.write('audio-stage-index.json',self.stage)
        self.limit=patch.object(batch,'ensure_audio_limit',return_value={'status':'updated'}).start();self.addCleanup(patch.stopall)
        self.register=patch.object(batch,'register_audio',side_effect=lambda client,row,apply=False:mapping(row)).start()

    def cleanup(self):
        if self.folder.parent.resolve()!=self.parent.resolve() or not self.folder.name.startswith('fixture-'):raise RuntimeError('unsafe_fixture_cleanup')
        shutil.rmtree(self.folder)
    def write(self,name,value): (self.folder/name).write_text(json.dumps(value),encoding='utf-8')
    def run_batch(self,apply=True,emit=None):return batch.register_staged_audio(self.store,self.client,self.events.append if emit is None else emit,apply)

    def test_full_source_preflight_precedes_registration_and_each_verified_entry_is_persisted(self):
        stage_before=(self.folder/'audio-stage-index.json').read_bytes();observed=[]
        def emit(event):
            observed.append(copy.deepcopy(event))
            if event['completed']:
                index=json.loads((self.folder/'audio-files-index.json').read_text())
                self.assertEqual(len(index['files']),event['completed'])
        result=self.run_batch(emit=emit)
        expected={key:mapping(row) for key,row in self.stage['files'].items()}
        self.assertEqual(result,expected);self.assertEqual(self.register.call_count,2)
        self.limit.assert_called_once_with(self.client,apply=True)
        self.assertTrue(all(call.kwargs=={'apply':True} for call in self.register.call_args_list))
        self.assertEqual(observed,[{'stage':'audio_register','completed':n,'total':2} for n in range(3)])
        self.assertEqual(json.loads((self.folder/'audio-files-index.json').read_text()),
            {'version':1,'account':ACCOUNT,'origin':ORIGIN,'site':SITE,'files':expected})
        self.assertEqual((self.folder/'audio-stage-index.json').read_bytes(),stage_before)
        self.assertNotIn('https://',json.dumps(result));self.assertEqual(list(self.folder.glob('*.tmp')),[])

    def test_partial_staging_wrong_source_or_corrupt_receipt_never_touch_mcp(self):
        original=copy.deepcopy(self.stage)
        self.stage['files'].pop(next(iter(self.stage['files'])));self.write('audio-stage-index.json',self.stage)
        with self.assertRaisesRegex(Stop,'audio_staging_incomplete'):self.run_batch()
        self.stage=original;self.write('audio-stage-index.json',self.stage)
        self.inventory['files'][0]['references'][0]['lesson_id']=1993;self.write('audio-inventory.json',self.inventory)
        with self.assertRaises(Stop):self.run_batch()
        self.limit.assert_not_called();self.register.assert_not_called();self.assertFalse((self.folder/'audio-files-index.json').exists())

    def test_unknown_second_write_preserves_first_checkpoint_then_resume_revalidates_all_entries(self):
        original=self.register.side_effect;counter=0
        def register(client,row,apply=False):
            nonlocal counter
            counter+=1
            if counter==2:raise Stop('audio_write_uncertain')
            return mapping(row)
        self.register.side_effect=register
        with self.assertRaisesRegex(Stop,'audio_write_uncertain'):self.run_batch()
        index=json.loads((self.folder/'audio-files-index.json').read_text());self.assertEqual(len(index['files']),1)
        self.register.reset_mock();self.register.side_effect=original
        self.assertEqual(len(self.run_batch()),2);self.assertEqual(self.register.call_count,2)

    def test_dry_run_plans_every_file_without_persistence_or_verified_events(self):
        result=self.run_batch(False)
        self.assertEqual(len(result),2);self.assertFalse((self.folder/'audio-files-index.json').exists());self.assertEqual(self.events,[])
        self.limit.assert_called_once_with(self.client,apply=False)
        self.assertTrue(all(call.kwargs=={'apply':False} for call in self.register.call_args_list))

    def test_resume_revalidates_mcp_without_replacing_an_unchanged_checkpoint(self):
        expected=self.run_batch()
        path=self.folder/'audio-files-index.json';before=path.read_bytes()
        self.register.reset_mock()
        with patch.object(batch,'_save_index',side_effect=AssertionError('unchanged index must not be replaced')) as save:
            self.assertEqual(self.run_batch(),expected)
        self.assertEqual(self.register.call_count,2)
        save.assert_not_called()
        self.assertEqual(path.read_bytes(),before)

    def test_foreign_or_changed_registration_index_is_rejected_before_mutations(self):
        key,row=next(iter(self.stage['files'].items()))
        original={'version':1,'account':ACCOUNT,'origin':ORIGIN,'site':SITE,'files':{key:mapping(row)}}
        for change in ('account','mapping','extra'):
            index=copy.deepcopy(original)
            if change=='account':index['account']='mv-centr'
            elif change=='mapping':index['files'][key]['file_url']='/private/files/other.mp3'
            else:index['files']['f'*64]=mapping(row)
            self.write('audio-files-index.json',index)
            with self.subTest(change=change),self.assertRaises(Stop):self.run_batch()
        self.limit.assert_not_called();self.register.assert_not_called()

    def test_callback_or_index_failure_stops_without_advancing_to_next_file(self):
        def fail(event):raise RuntimeError('PRIVATE CALLBACK')
        with self.assertRaises(Stop) as caught:self.run_batch(emit=fail)
        self.assertNotIn('PRIVATE',str(caught.exception));self.limit.assert_not_called();self.register.assert_not_called()
        def fail_after_first(event):
            if event['completed']:raise RuntimeError('PRIVATE CALLBACK')
        with self.assertRaises(Stop):self.run_batch(emit=fail_after_first)
        self.assertEqual(self.register.call_count,1);self.assertEqual(len(json.loads((self.folder/'audio-files-index.json').read_text())['files']),1)
        self.register.reset_mock()
        with patch.object(batch,'_save_index',side_effect=Stop('audio_index_write_failed')):
            with self.assertRaises(Stop):self.run_batch()
        self.assertEqual(self.register.call_count,2)
        self.assertEqual(len(json.loads((self.folder/'audio-files-index.json').read_text())['files']),1)

    def test_invalid_mapping_binding_and_apply_never_create_unverified_index(self):
        self.client.site='my-lk.iomp.ru'
        with self.assertRaises(Stop):self.run_batch()
        self.limit.assert_not_called();self.register.assert_not_called()
        self.client.site=SITE
        with self.assertRaises(Stop):self.run_batch(1)
        self.register.side_effect=lambda client,row,apply=False:dict(mapping(row),size=999)
        with self.assertRaises(Stop):self.run_batch()
        self.assertFalse((self.folder/'audio-files-index.json').exists())


if __name__=='__main__':unittest.main()

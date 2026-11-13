"""Offline audit fixtures only: no real archive, media fetches, or MCP."""
from contextlib import closing
import copy
import hashlib
import json
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import uuid

import audit as mod
import storage
import lesson_policy
from importer import Review
from test_normalize_audio import audio, key, receipt

SYNTHETIC_PENDING = {'DEFERRED':{557:frozenset({5952}),598:frozenset({7544})}, 'EXCLUDED':{}}


def record(parsed):
    return {'account':'mastervision','origin':'https://shop.mastervision.su','html':'PRIVATE HTML',
            'verified':True,'error':None,'parsed':parsed}


class AuditTests(unittest.TestCase):
    def test_permanent_exclusions_are_known_metadata_and_do_not_block_course(self):
        self.course(207,(11,1976,12));self.course(445,(21,4089,22))
        before=self.path.read_bytes()
        with patch.object(mod,'normalize_payload',wraps=mod.normalize_payload) as normalize:
            report=mod.audit_remaining(self.folder)
        self.assertEqual([c.args[0]['lesson_id'] for c in normalize.call_args_list],[11,12,21,22])
        self.assertEqual(report['summary']['known_excluded_lessons'],2)
        self.assertEqual(report['summary']['planned_lessons'],4)
        self.assertEqual(report['summary']['lessons'],6)
        for course,lid,planned in zip(report['courses'],(1976,4089),([11,12],[21,22])):
            self.assertTrue(course['pure_ready']);self.assertEqual(course['issues'],[])
            self.assertEqual(course['known_excluded'],[{'lesson_id':lid,'code':'owner_excluded_obsolete_lesson'}])
            self.assertEqual(course['planned_lesson_ids'],planned);self.assertEqual(course['deferred_lesson_ids'],[])
        self.assertEqual(before,self.path.read_bytes())

    @patch.multiple(lesson_policy, **SYNTHETIC_PENDING)
    def test_partial_keeps_deferred_source_and_audits_only_selected_lessons(self):
        self.course(598,(1,7544,2),state='partial')
        before=self.path.read_bytes()
        with patch.object(mod,'normalize_payload',wraps=mod.normalize_payload) as normalize:
            report=mod.audit_remaining(self.folder)
        course=report['courses'][0]
        self.assertEqual([c.args[0]['lesson_id'] for c in normalize.call_args_list],[1,2])
        self.assertEqual(course['lesson_ids'],[1,7544,2]);self.assertEqual(course['ready_lessons'],2)
        self.assertEqual(course['deferred_lesson_ids'],[7544]);self.assertEqual(course['state'],'partial')
        self.assertFalse(course['pure_ready']);self.assertFalse(course['candidate_for_media_preflight'])
        self.assertEqual(course['issues'],[{'lesson_id':7544,'codes':['owner_deferred_lesson']}])
        self.assertEqual(report['summary']['partial_courses'],1)
        self.assertEqual(report['summary']['deferred_lessons'],1)
        self.assertEqual(before,self.path.read_bytes())

    def test_final_owner_exclusions_are_ready_without_pending_or_false_lesson_counts(self):
        self.course(557,(5941,5952,5942));self.course(598,(7543,7544,7545))
        before=self.path.read_bytes()
        report=mod.audit_remaining(self.folder)
        self.assertEqual(report['summary']['known_excluded_lessons'],2)
        self.assertEqual(report['summary']['planned_lessons'],4)
        self.assertEqual(report['summary']['deferred_lessons'],0)
        for course,lid in zip(report['courses'],(5952,7544)):
            self.assertTrue(course['pure_ready']);self.assertEqual(course['ready_lessons'],2)
            self.assertEqual(course['deferred_lesson_ids'],[])
            self.assertEqual(course['known_excluded'],[{'lesson_id':lid,'code':'owner_excluded_obsolete_lesson'}])
            self.assertNotIn(lid,course['planned_lesson_ids'])
        self.assertEqual(before,self.path.read_bytes())

    def setUp(self):
        self.parent=Path(__file__).resolve().parents[3]/'.tmp-mastervision-audit-tests'
        self.parent.mkdir(exist_ok=True);self.folder=self.parent/('fixture-'+uuid.uuid4().hex)
        self.folder.mkdir();self.path=self.folder/'mastervision-migration.sqlite'
        self.addCleanup(self.cleanup)
        with storage.Store(self.folder):pass

    def cleanup(self):
        if self.folder.parent.resolve()!=self.parent.resolve() or not self.folder.name.startswith('fixture-'):
            raise RuntimeError('unsafe_fixture_cleanup')
        shutil.rmtree(self.folder)

    def course(self,cid=7,lids=(11,),nodes=None,state='review',checkpoint=True):
        with storage.Store(self.folder) as store:
            store.catalog([{'id':cid,'title':'PRIVATE COURSE'}])
            if not checkpoint:return
            course={'course_id':cid,'title':'PRIVATE COURSE','lesson_ids':list(lids),
                    'lessons':[{'id':lid,'title':'PRIVATE LESSON'} for lid in lids]}
            digest=store.capture('course',cid,0,record(course));pairs=[]
            for lid in lids:
                payload={'account':'mastervision','source_origin':'https://shop.mastervision.su',
                    'course_id':cid,'lesson_id':lid,'course_title':'PRIVATE COURSE','lesson_title':'PRIVATE LESSON',
                    'format':'ape','ape':{'name':'page','children':copy.deepcopy(nodes if nodes is not None else [
                        {'name':'text','fields':{'html':'<p>PRIVATE BODY {name}</p>'}}])}}
                pairs.append((lid,store.capture('lesson',cid,lid,record({'payload':payload}))))
            store.bind_course(cid,digest,pairs);store.mark(cid,state)

    def test_all_unfinished_courses_ordered_and_no_payload_or_credentials_in_report(self):
        self.course(lids=(12,11));self.course(8,(81,),state='imported');self.course(9,(91,),state='collected')
        before=self.path.read_bytes();progress=[]
        with patch.object(storage.Store,'__init__',side_effect=AssertionError('must not open writer')):
            report=mod.audit_remaining(self.folder,progress=progress.append)
        self.assertEqual(report['summary']['remaining_courses'],2)
        self.assertEqual(report['summary']['state_counts'],{'review':1,'collected':1})
        self.assertEqual([c['course_id'] for c in report['courses']],[7,9])
        self.assertEqual(report['courses'][0]['lesson_ids'],[12,11])
        self.assertTrue(report['courses'][0]['pure_ready'])
        self.assertEqual(report['courses'][0]['media_availability'],'unverified')
        self.assertEqual(progress[-1]['status'],'completed')
        self.assertEqual(before,self.path.read_bytes())
        self.assertNotIn('PRIVATE',json.dumps(report));self.assertNotIn('PRIVATE',json.dumps(progress))

    def test_pending_missing_source_and_empty_course_remain_visible(self):
        self.course(7,checkpoint=False);self.course(8,(),state='empty')
        report=mod.audit_remaining(self.folder)
        self.assertEqual(report['summary']['remaining_courses'],2)
        self.assertEqual(report['summary']['state_counts'],{'pending':1,'empty':1})
        self.assertFalse(report['courses'][0]['pure_ready'])
        self.assertTrue(report['courses'][1]['pure_ready'])
        self.assertEqual(report['courses'][1]['planned_lesson_ids'],[])

    def test_missing_collection_checkpoint_retains_latest_specific_lesson_diagnostic(self):
        self.course(317,checkpoint=False)
        with storage.Store(self.folder) as store:
            store.mark(317,'review');store.event('collect',317,2314,'review',['ape_root_unrecognized'])
        report=mod.audit_remaining(self.folder)
        self.assertEqual(report['summary']['collection_failures'],1)
        self.assertEqual(report['courses'][0]['collection_failure'],{'lesson_id':2314,'codes':['ape_root_unrecognized']})
        self.assertFalse(report['courses'][0]['pure_ready'])

    def test_normalizer_review_uses_exact_raw_core_fallback_and_records_review_code(self):
        self.course()
        with patch.object(mod,'normalize_payload',side_effect=Review('static_table_requires_review')):
            report=mod.audit_remaining(self.folder)
        course=report['courses'][0]
        self.assertTrue(course['pure_ready'])
        self.assertEqual(course['normalization_reviews'],[{'lesson_id':11,'code':'static_table_requires_review'}])
        self.assertEqual(report['summary']['normalization_reviews'],1)

    def test_fatal_normalization_identity_error_is_not_downgraded(self):
        self.course()
        for code in mod.FATAL:
            with patch.object(mod,'normalize_payload',side_effect=Review(code)),self.assertRaisesRegex(mod.AuditError,'^'+code+'$'):
                mod.audit_remaining(self.folder)

    def test_default_audio_index_is_bound_and_native_audio_keys_are_metadata_only(self):
        self.course(nodes=[audio()])
        index={'version':1,'account':'mastervision','origin':'https://shop.mastervision.su',
               'site':'my-lk.mastervision.su','files':{key():receipt()}}
        (self.folder/'audio-files-index.json').write_text(json.dumps(index),encoding='utf-8')
        course=mod.audit_remaining(self.folder)['courses'][0]
        self.assertTrue(course['pure_ready']);self.assertTrue(course['uses_audio'])
        self.assertEqual(course['audio_keys'],[key()]);self.assertNotIn('autoweboffice',json.dumps(course))
        index['account']='mv-centr';(self.folder/'audio-files-index.json').write_text(json.dumps(index),encoding='utf-8')
        with self.assertRaisesRegex(mod.AuditError,'audit_audio_index_invalid'):mod.audit_remaining(self.folder)

    def test_invalid_receipt_or_foreign_site_mapping_rejected(self):
        self.course(nodes=[audio()])
        for value in ({key():receipt(file_url='https://other.example/file.mp3')},{key():receipt(size=True)},[]):
            with self.assertRaisesRegex(mod.AuditError,'audit_audio_index_invalid'):
                mod.audit_remaining(self.folder,audio_assets=value)

    def test_foreign_source_guard_precedes_normalization_or_audio_loading(self):
        self.course()
        with closing(sqlite3.connect(self.path)) as db,db:db.execute("UPDATE meta SET account='iomp'")
        before=self.path.read_bytes()
        with patch.object(mod,'normalize_payload') as normalize,self.assertRaisesRegex(mod.AuditError,'audit_account_mismatch'):
            mod.audit_remaining(self.folder)
        normalize.assert_not_called();self.assertEqual(before,self.path.read_bytes())

    def test_synthetic_image_preparation_never_fetches_media(self):
        image={'id':'image-id','name':'image','fields':{'anchor':'','imageSrc':'https://f1.autoweboffice.com/synthetic.jpg'}}
        self.course(nodes=[image])
        with patch('urllib.request.OpenerDirector.open',side_effect=AssertionError('network forbidden')):
            report=mod.audit_remaining(self.folder)
        self.assertTrue(report['courses'][0]['pure_ready']);self.assertEqual(report['courses'][0]['images'],1)

    def test_unknown_image_host_is_reported_without_fetching(self):
        self.course(nodes=[{'id':'photo','name':'image','fields':{'imageSrc':'https://foreign.example/private.jpg'}}])
        report=mod.audit_remaining(self.folder);course=report['courses'][0]
        self.assertFalse(course['pure_ready'])
        self.assertEqual(course['images'],1)
        self.assertEqual(course['issues'],[{'lesson_id':11,'codes':['asset_host_requires_review']}])

    def test_cli_writes_only_fixed_private_report_and_safe_progress(self):
        self.course()
        before=self.path.read_bytes()
        result=subprocess.run([sys.executable,'-B',str(Path(mod.__file__).resolve()),
            '--directory',str(self.folder),'--output'],cwd=Path(__file__).resolve().parents[2],
            capture_output=True,check=True,timeout=15)
        progress=[json.loads(line) for line in result.stdout.decode().splitlines()]
        self.assertEqual(progress[-1]['status'],'completed')
        report=json.loads((self.folder/'remaining-audit.json').read_bytes())
        self.assertEqual(report['summary']['review_courses'],1)
        self.assertNotIn('PRIVATE',json.dumps(report));self.assertNotIn(b'PRIVATE',result.stdout)
        self.assertEqual(before,self.path.read_bytes())

    def test_known_historical_404_is_distinct_from_pure_readiness(self):
        source='https://f1.autoweboffice.com/synthetic.jpg'
        nodes=[{'name':'text','fields':{'html':'Body'}} for _ in range(7)]+[
            {'id':'photo','name':'image','fields':{'imageSrc':source}}]
        self.course(280,(1802,),nodes=nodes);self.course(286,(1857,),nodes=nodes)
        digest=hashlib.sha256(source.encode()).hexdigest()
        with patch.dict(mod.KNOWN_404,{(280,1802):digest,(286,1857):digest},clear=True):
            report=mod.audit_remaining(self.folder)
        self.assertEqual(report['summary']['pure_ready_courses'],2)
        self.assertEqual(report['summary']['known_media_blocked_courses'],2)
        for course in report['courses']:
            self.assertTrue(course['pure_ready']);self.assertFalse(course['candidate_for_media_preflight'])
            self.assertEqual(course['media_availability'],'known_prior_404')

    def test_changed_source_or_removed_image_does_not_keep_obsolete_404_flag(self):
        source='https://f1.autoweboffice.com/synthetic.jpg'
        nodes=[{'name':'text','fields':{'html':'Body'}} for _ in range(7)]+[
            {'id':'photo','name':'image','fields':{'imageSrc':source}}]
        self.course(280,(1802,),nodes=nodes)
        with patch.dict(mod.KNOWN_404,{(280,1802):'a'*64},clear=True):
            course=mod.audit_remaining(self.folder)['courses'][0]
        self.assertEqual(course['known_asset_errors'],[])
        digest=hashlib.sha256(source.encode()).hexdigest()
        def omit(payload,**kwargs):
            result=copy.deepcopy(payload);result['ape']['children'].pop(7);return result,[]
        with patch.dict(mod.KNOWN_404,{(280,1802):digest},clear=True),patch.object(mod,'normalize_payload',side_effect=omit):
            course=mod.audit_remaining(self.folder)['courses'][0]
        self.assertEqual(course['known_asset_errors'],[]);self.assertTrue(course['candidate_for_media_preflight'])

    def test_capture_corruption_is_detected_without_writing_source(self):
        self.course()
        with closing(sqlite3.connect(self.path)) as db,db:db.execute("UPDATE captures SET payload=x'00' WHERE kind='lesson'")
        before=self.path.read_bytes()
        with self.assertRaisesRegex(mod.AuditError,'audit_capture_invalid'):mod.audit_remaining(self.folder)
        self.assertEqual(before,self.path.read_bytes())

    def test_sqlite_readers_close_before_normalizing_and_other_writer_can_commit(self):
        self.course();self.course(8,(81,))
        with closing(sqlite3.connect(self.path)) as db,db:
            db.execute('PRAGMA journal_mode=DELETE');db.execute('CREATE TABLE writer_probe(value)')
        original_connect=sqlite3.connect;opened=[];normalize=mod.normalize_payload
        class Tracked:
            def __init__(self,*a,**k):self.db=original_connect(*a,**k);self.closed=False;opened.append(self)
            @property
            def row_factory(self):return self.db.row_factory
            @row_factory.setter
            def row_factory(self,value):self.db.row_factory=value
            def execute(self,*a,**k):return self.db.execute(*a,**k)
            def close(self):self.db.close();self.closed=True
        def checked_normalize(*a,**k):
            self.assertTrue(all(connection.closed for connection in opened))
            with closing(original_connect(self.path,timeout=0)) as db,db:
                db.execute('BEGIN EXCLUSIVE');db.execute('INSERT INTO writer_probe VALUES(1)')
            return normalize(*a,**k)
        with patch.object(mod.sqlite3,'connect',Tracked),patch.object(mod,'normalize_payload',side_effect=checked_normalize):
            report=mod.audit_remaining(self.folder)
        self.assertEqual(report['summary']['review_courses'],2)
        self.assertTrue(all(connection.closed for connection in opened))


if __name__=='__main__':unittest.main()

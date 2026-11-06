import tempfile
import hashlib
import json
import sqlite3
import unittest
from pathlib import Path
from unittest.mock import patch

import frappe_batch_import as mod


def payload(lesson):
    return {'account':'mv-centr','source_origin':mod.ORIGIN,'course_id':24,'lesson_id':lesson,
            'course_title':'Course','lesson_title':'Lesson','format':'ape','ape':{'name':'page','children':[]}}


class Journal:
    def __init__(self):self.events=[]
    def event(self,*args):self.events.append(args)


class Client:
    def __init__(self,unsupported=None,write_fails=False):
        self.existing=[]; self.unsupported=unsupported; self.write_fails=write_fails; self.writes=[]
    def call(self,name,args):
        if name != 'call_method':raise AssertionError('unexpected request')
        p=args['args']['payload']; ident=p['lesson_id']; dry=args['args']['dry_run']
        if not dry:
            self.writes.append(ident)
            if self.write_fails:raise mod.Stop('connection_lost')
            self.existing.append(ident)
            return {'result':{'action':'created'}}
        return {'result':{'account':'mv-centr','course_id':'24','lesson_id':str(ident),'dry_run':True,
            'ready':ident!=self.unsupported,'issues':['unknown_block'] if ident==self.unsupported else [],
            'warnings':[],'action':'already_imported' if ident in self.existing else 'create_lesson'}}


class BatchTests(unittest.TestCase):
    def test_long_course_title_is_reported_before_writes(self):
        client=Client();journal=Journal();p=payload(1);p['course_title']='x'*141
        with patch.object(mod,'prepare_course',return_value=[p]),patch.object(mod,'outline',return_value=[]):
            with self.assertRaisesRegex(mod.Review,'course_needs_review'):mod.import_course(client,journal,24,[1],True)
        self.assertEqual(client.writes,[])
        self.assertIn((24,1,'lesson_needs_review',['course_title_exceeds_frappe_limit']),journal.events)

    def test_reviewed_image_requires_matching_source_and_bytes(self):
        import base64
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory); raw=b'fixture image'; (root/'image.jpg').write_bytes(raw)
            source='https://example.test/image.jpg';p=payload(1)
            p['ape']['children']=[{'name':'image','id':'picture','fields':{'imageSrc':source}}]
            rule={(24,1,'picture'):(hashlib.sha256(source.encode()).hexdigest(),hashlib.sha256(raw).hexdigest(),'image.jpg')}
            with patch.object(mod,'DATA',root),patch.object(mod,'REVIEWED_IMAGES',rule):
                self.assertEqual(base64.b64decode(mod.prepared_images(p)['picture']),raw)
                (root/'image.jpg').write_bytes(b'changed')
                with self.assertRaisesRegex(mod.Review,'image_requires_preparation'):mod.prepared_images(p)
                (root/'image.jpg').write_bytes(raw);p['ape']['children'][0]['fields']['imageSrc']+='changed'
                with self.assertRaisesRegex(mod.Review,'image_requires_preparation'):mod.prepared_images(p)

    def test_outline_batches_reads_and_preserves_source_order(self):
        class OutlineClient:
            def __init__(self): self.groups=[]; self.omit=False; self.wrong_account=False
            def call(self,name,args):
                if name=='get_document':
                    if args['doctype']=='LMS Course': return {'chapters':[{'chapter':'chapter'}]}
                    return {'name':'chapter','course':'course','is_scorm_package':0,
                            'lessons':[{'idx':i,'lesson':str(i)} for i in range(1,202)]}
                if args['doctype']=='LMS Course': return {'documents':[{'name':'course','published':0}]}
                group=args['filters'][0][2]; self.groups.append(group)
                docs=[{'name':n,'custom_avo_id':n,'custom_avo_account':'other' if self.wrong_account else mod.ACCOUNT,
                       'course':'course','chapter':'chapter','is_draft':1,'include_in_preview':0} for n in reversed(group)]
                return {'documents':docs[:-1] if self.omit else docs,'has_next_page':False}
        client=OutlineClient()
        self.assertEqual(mod.outline(client,21),list(range(1,202)))
        self.assertEqual([len(g) for g in client.groups],[100,100,1])
        client.omit=True
        with self.assertRaisesRegex(mod.Review,'course_outline_invalid'):mod.outline(client,21)
        client.omit=False; client.wrong_account=True
        with self.assertRaisesRegex(mod.Review,'existing_lesson_not_safe'):mod.outline(client,21)

    def test_catalog_course_with_missing_manifest_is_not_silently_skipped(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            def db(name, statements):
                c=sqlite3.connect(root/name)
                for sql,args in statements:c.execute(sql,args)
                c.commit();c.close()
            db('mv-centr-captures.sqlite', [('create table capture_meta(singleton integer,account text,origin text)',()),
                ('insert into capture_meta values(1,?,?)',(mod.ACCOUNT,mod.ORIGIN))])
            db('mv-centr-queue.sqlite',[('create table queue_meta(singleton integer,origin text)',()),
                ('insert into queue_meta values(1,?)',(mod.ORIGIN,))])
            raw='[101]';digest=hashlib.sha256(raw.encode()).hexdigest()
            db('mv-centr-course-manifests.sqlite', [('create table manifest_meta(singleton integer,account text,origin text)',()),
                ('insert into manifest_meta values(1,?,?)',(mod.ACCOUNT,mod.ORIGIN)),
                ('create table course_manifests(id integer,course_id integer,lesson_ids text,sha256 text,state text)',()),
                ('insert into course_manifests values(1,11,?,?,?)',(raw,digest,'accepted'))])
            db('mv-centr-course-catalog.sqlite',[('create table catalog_meta(singleton integer,account text,origin text)',()),
                ('insert into catalog_meta values(1,?,?)',(mod.ACCOUNT,mod.ORIGIN)),
                ('create table catalog_pages(run_id text,page integer,total integer,start integer,end integer,course_ids text,observed_at text)',()),
                ('insert into catalog_pages values(?,?,?,?,?,?,?)',('run',1,2,1,2,json.dumps([10,11]),'2026'))])
            with patch.object(mod,'DATA',root):
                self.assertEqual(mod.course_ids(),[(10,None),(11,[101])])

    def test_test_lesson_17_is_excluded_without_excluding_course_17(self):
        client=Client();journal=Journal()
        with patch.object(mod,'prepare_course',side_effect=AssertionError('should not fetch')):
            self.assertEqual(mod.import_course(client,journal,8,[17],True),'excluded')
        self.assertEqual(client.writes,[])
        self.assertIn((8,17,'lesson_excluded',['user_excluded_test_lesson']),journal.events)
        with patch.object(mod,'prepare_course',return_value=[payload(1),payload(17),payload(2)]), \
                patch.object(mod,'outline',side_effect=lambda client,course:list(client.existing)):
            mod.import_course(client,journal,17,[1,17,2],True)
        self.assertEqual(client.writes,[1,2])

    def run_course(self,client,journal,apply=True,order=(1,2)):
        with patch.object(mod,'prepare_course',return_value=[payload(x) for x in order]), \
                patch.object(mod,'outline',side_effect=lambda client,course: list(client.existing)):
            mod.import_course(client,journal,24,list(order),apply)

    def test_preflight_entire_course_before_any_writes(self):
        client=Client(unsupported=2);journal=Journal()
        with self.assertRaisesRegex(mod.Review,'course_needs_review'):self.run_course(client,journal)
        self.assertEqual(client.writes,[])
        self.assertIn((24,2,'lesson_needs_review',['unknown_block']),journal.events)

    def test_draft_import_preserves_order_and_rechecks_each_lesson(self):
        client=Client();journal=Journal();self.run_course(client,journal)
        self.assertEqual(client.writes,[1,2]);self.assertEqual(client.existing,[1,2])
        self.assertIn((24,None,'course_created'),journal.events)
        self.run_course(client,journal)
        self.assertEqual(client.writes,[1,2])
        self.assertIn((24,None,'existing_structure_unverified'),journal.events)

    def test_invalid_existing_order_stops_without_writes(self):
        client=Client();client.existing=[2]
        with self.assertRaisesRegex(mod.Review,'course_order_conflict'):self.run_course(client,Journal())
        self.assertEqual(client.writes,[])

    def test_uncertain_write_stops_immediately(self):
        client=Client(write_fails=True)
        journal=Journal()
        with self.assertRaisesRegex(mod.Stop,'write_result_uncertain'):self.run_course(client,journal)
        self.assertEqual(client.writes,[1])
        self.assertIn((24,1,'write_uncertain',['write_result_uncertain']),journal.events)

    def test_unprepared_image_blocks_the_whole_course(self):
        client=Client(); journal=Journal(); second=payload(2)
        second['ape']['children']=[{'name':'image','id':'example','fields':{'imageSrc':'https://example.test/img.jpg'}}]
        with patch.object(mod,'prepare_course',return_value=[payload(1),second]), \
                patch.object(mod,'outline',return_value=[]):
            with self.assertRaisesRegex(mod.Review,'course_needs_review'):
                mod.import_course(client,journal,24,[1,2],True)
        self.assertEqual(client.writes,[])
        self.assertIn((24,2,'lesson_needs_review',['image_requires_preparation']),journal.events)

    def test_three_failures_pause_and_explicit_resume_clears(self):
        with tempfile.TemporaryDirectory() as directory:
            j=mod.Journal(Path(directory)/'events.sqlite')
            try:
                self.assertFalse(j.failure());self.assertFalse(j.failure());self.assertTrue(j.failure())
                self.assertEqual(j.state(),(1,3));j.resume();self.assertEqual(j.state(),(0,0))
            finally:j.close()


if __name__=='__main__':unittest.main()

import tempfile
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

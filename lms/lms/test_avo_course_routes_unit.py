import importlib.util
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch


class AvoRoutesTest(unittest.TestCase):
    def setUp(self):
        self.rows={
            'LMS Course':[{'name':'course-a','custom_avo_account':'mv-centr','custom_avo_id':'11'}],
            'Course Lesson':[{'name':'lesson-a','custom_avo_account':'mv-centr','custom_avo_id':'26','course':'course-a','chapter':'chapter-a'}],
            'Chapter Reference':[{'parent':'course-a','parenttype':'LMS Course','chapter':'chapter-a','idx':2}],
            'Lesson Reference':[{'parent':'chapter-a','parenttype':'Course Chapter','lesson':'lesson-a','idx':3}],
        }
        self.allow_course=True;self.allow_lesson=True;self.locked=set()
        f=types.ModuleType('frappe');f.local=types.SimpleNamespace(site='my-lk.mv-centr.ru')
        f.whitelist=lambda **kw:lambda fn:fn
        def matches(row,filters):
            for key,value in filters.items():
                if isinstance(value,list) and value[0]=='in':
                    if row.get(key) not in value[1]:return False
                elif row.get(key)!=value:return False
            return True
        def get_all(doctype,filters,fields,limit_page_length):
            rows=[{k:r.get(k) for k in fields} for r in self.rows[doctype] if matches(r,filters)]
            return rows[:limit_page_length] if limit_page_length else rows
        def get_value(doctype,name,fields,as_dict):
            return next(({k:r.get(k) for k in fields} for r in self.rows[doctype] if r['name']==name),None)
        f.get_all=get_all;f.db=types.SimpleNamespace(get_value=get_value)
        imp=types.ModuleType('lms.lms.avo_import');imp.SITE_ACCOUNTS={'my-lk.mv-centr.ru':('mv-centr','example'),'my-lk.iomp.ru':('iomp','example')}
        util=types.ModuleType('lms.lms.utils');util.can_view_course=lambda course:self.allow_course;util.guest_access_allowed=lambda:True
        perm=types.ModuleType('lms.lms.permissions');perm.can_access_lesson=lambda lesson:self.allow_lesson;perm.get_lesson_gate=lambda course:(self.locked,None)
        self.modules=patch.dict(sys.modules,{'frappe':f,'lms.lms.avo_import':imp,'lms.lms.utils':util,'lms.lms.permissions':perm})
        self.modules.start();self.addCleanup(self.modules.stop);self.frappe=f
        spec=importlib.util.spec_from_file_location('avo_routes',Path(__file__).with_name('avo_course_routes.py'))
        self.mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(self.mod)

    def test_course_and_lesson_round_trip(self):
        self.assertEqual(self.mod.resolve('11'),{'course_name':'course-a'})
        self.assertEqual(self.mod.resolve('11','26'),{'course_name':'course-a','lesson_name':'lesson-a','chapter_number':2,'lesson_number':3})
        self.assertEqual(self.mod.canonical('course-a','2','3'),{'course_id':'11','lesson_id':'26'})

    def test_access_is_checked_for_both_directions(self):
        self.allow_course=False
        self.assertIsNone(self.mod.resolve('11'));self.assertIsNone(self.mod.canonical('course-a'))
        self.allow_course=True;self.allow_lesson=False
        self.assertIsNone(self.mod.resolve('11','26'));self.assertIsNone(self.mod.canonical('course-a','2','3'))
        self.allow_lesson=True;self.locked={'lesson-a'}
        self.assertIsNone(self.mod.resolve('11','26'));self.assertIsNone(self.mod.canonical('course-a','2','3'))

    def test_cross_account_wrong_course_and_invalid_ids_fail_closed(self):
        self.frappe.local.site='my-lk.iomp.ru';self.assertIsNone(self.mod.resolve('11','26'))
        self.frappe.local.site='unknown';self.assertIsNone(self.mod.resolve('11'))
        self.frappe.local.site='my-lk.mv-centr.ru'
        for value in ('0','../11','011','１１','1'*21):self.assertIsNone(self.mod.resolve(value))
        self.rows['Course Lesson'][0]['course']='another-course'
        self.assertIsNone(self.mod.resolve('11','26'))

    def test_duplicate_id_or_ambiguous_placement_never_guesses(self):
        self.rows['LMS Course'].append(dict(self.rows['LMS Course'][0],name='another-course'))
        self.assertIsNone(self.mod.resolve('11'))
        self.rows['LMS Course'].pop()
        self.rows['Lesson Reference'].append(dict(self.rows['Lesson Reference'][0],idx=4))
        self.assertIsNone(self.mod.resolve('11','26'));self.assertIsNone(self.mod.canonical('course-a','2','3'))

    def test_reordering_changes_position_not_source_url(self):
        self.rows['Chapter Reference'][0]['idx']=4;self.rows['Lesson Reference'][0]['idx']=9
        self.assertEqual(self.mod.resolve('11','26')['chapter_number'],4)
        self.assertEqual(self.mod.resolve('11','26')['lesson_number'],9)

    def test_duplicate_positions_and_mismatched_chapter_are_refused(self):
        self.rows['Chapter Reference'].append({'parent':'course-a','parenttype':'LMS Course','chapter':'other','idx':2})
        self.assertIsNone(self.mod.resolve('11','26'))
        self.rows['Chapter Reference'].pop()
        self.rows['Lesson Reference'].append({'parent':'chapter-a','parenttype':'Course Chapter','lesson':'other','idx':3})
        self.assertIsNone(self.mod.resolve('11','26'))
        self.rows['Lesson Reference'].pop()
        self.rows['Course Lesson'][0]['chapter']='other'
        self.assertIsNone(self.mod.resolve('11','26'))

    def test_reordering_during_fetch_cannot_return_another_lesson(self):
        utils=sys.modules['lms.lms.utils']
        utils.get_lesson=lambda **kwargs:{'name':'different-lesson','content':'private'}
        self.assertEqual(self.mod.get_lesson_by_source('11','26'),{'locked':1,'not_found':1})
        utils.get_lesson=lambda **kwargs:{'name':'lesson-a','content':'correct'}
        self.assertEqual(self.mod.get_lesson_by_source('11','26')['content'],'correct')
        self.allow_lesson=False
        self.assertEqual(self.mod.get_lesson_by_source('11','26'),{'locked':1,'not_found':1})


if __name__=='__main__':unittest.main()

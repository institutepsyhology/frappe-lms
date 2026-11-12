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
            'Course Chapter':[{'name':'chapter-a','title':'Chapter'}],
        }
        self.allow_course=True;self.allow_lesson=True;self.allow_edit=True;self.allow_write=True;self.locked=set();self.saved=[]
        self.resume=None;self.membership=False;self.ordered=[{'name':'lesson-a'}]
        f=types.ModuleType('frappe');f.local=types.SimpleNamespace(site='my-lk.mv-centr.ru')
        f.whitelist=lambda **kw:lambda fn:fn
        f.PermissionError=PermissionError;f.ValidationError=ValueError
        f.throw=lambda message,typ:(_ for _ in ()).throw(typ(message))
        def matches(row,filters):
            for key,value in filters.items():
                if isinstance(value,list) and value[0]=='in':
                    if row.get(key) not in value[1]:return False
                elif row.get(key)!=value:return False
            return True
        def get_all(doctype,filters,fields,limit_page_length):
            rows=[{k:r.get(k) for k in fields} for r in self.rows[doctype] if matches(r,filters)]
            return rows[:limit_page_length] if limit_page_length else rows
        def get_value(doctype,name,fields,as_dict=False):
            row=next((r for r in self.rows[doctype] if r['name']==name),None)
            if not row:return None
            return row.get(fields) if isinstance(fields,str) else {k:row.get(k) for k in fields}
        class Doc:
            def __init__(self,row):self.row=row
            def get(self,key):return self.row.get(key)
            def update(self,values):self.row.update(values)
            def save(self):self_saved.append(self.row['name'])
        self_saved=self.saved
        f.get_doc=lambda doctype,name:Doc(next(r for r in self.rows[doctype] if r['name']==name))
        f.has_permission=lambda *args,**kwargs:self.allow_write
        f.parse_json=lambda x:x
        f.get_all=get_all;f.db=types.SimpleNamespace(get_value=get_value,sql=lambda *args:None)
        imp=types.ModuleType('lms.lms.avo_import');imp.SITE_ACCOUNTS={'my-lk.mv-centr.ru':('mv-centr','example'),'my-lk.iomp.ru':('iomp','example')}
        util=types.ModuleType('lms.lms.utils');util.can_view_course=lambda course:self.allow_course;util.guest_access_allowed=lambda:True;util.can_modify_course=lambda course:self.allow_edit
        util.get_membership=lambda course:self.membership;util.get_ordered_lesson_rows=lambda course:self.ordered
        perm=types.ModuleType('lms.lms.permissions');perm.can_access_lesson=lambda lesson:self.allow_lesson;perm.get_lesson_gate=lambda course:(self.locked,self.resume)
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

    def test_course_cards_only_receive_unique_ids_from_current_site(self):
        cards=[{'name':'course-a'},{'name':'native-course'}]
        self.assertEqual(self.mod.annotate_course_ids(cards)[0]['avo_course_id'],'11')
        self.assertNotIn('avo_course_id',cards[1])
        self.rows['LMS Course'].append(dict(self.rows['LMS Course'][0],name='duplicate'))
        self.assertNotIn('avo_course_id',self.mod.annotate_course_ids([{'name':'course-a'}])[0])

    def test_editor_requires_course_author_and_document_write_permission(self):
        self.assertEqual(self.mod.resolve_editor('11','26')['lesson_name'],'lesson-a')
        self.allow_edit=False
        self.assertIsNone(self.mod.resolve_editor('11','26'))
        with self.assertRaises(PermissionError):self.mod.get_editor_by_source('11','26')
        self.allow_edit=True;self.allow_write=False
        with self.assertRaises(PermissionError):self.mod.get_editor_by_source('11','26')

    def test_lesson_only_editor_resolves_course_id_without_exposing_other_accounts(self):
        self.assertEqual(self.mod.resolve_editor_by_lesson('26'),
                         {'course_name':'course-a','lesson_name':'lesson-a',
                          'chapter_number':2,'lesson_number':3,'course_id':'11'})
        self.frappe.local.site='my-lk.iomp.ru'
        self.assertIsNone(self.mod.resolve_editor_by_lesson('26'))
        self.frappe.local.site='unknown'
        self.assertIsNone(self.mod.resolve_editor_by_lesson('26'))
        self.frappe.local.site='my-lk.mv-centr.ru'
        self.rows['LMS Course'][0]['custom_avo_account']='iomp'
        self.assertIsNone(self.mod.resolve_editor_by_lesson('26'))

    def test_lesson_only_editor_rejects_invalid_and_ambiguous_ids(self):
        for value in (None,26,'0','026','../26','２６','1'*21,['26']):
            self.assertIsNone(self.mod.resolve_editor_by_lesson(value))
        self.rows['Course Lesson'].append(dict(self.rows['Course Lesson'][0],name='duplicate',course='other-course'))
        self.assertIsNone(self.mod.resolve_editor_by_lesson('26'))
        self.rows['Course Lesson'].pop()
        self.rows['LMS Course'].append(dict(self.rows['LMS Course'][0],name='other-course'))
        self.assertIsNone(self.mod.resolve_editor_by_lesson('26'))
        self.rows['LMS Course'].pop()
        self.rows['LMS Course'][0]['custom_avo_id']='011'
        self.assertIsNone(self.mod.resolve_editor_by_lesson('26'))

    def test_lesson_only_editor_checks_membership_and_permissions(self):
        self.allow_edit=False
        self.assertIsNone(self.mod.resolve_editor_by_lesson('26'))
        self.allow_edit=True;self.allow_write=False
        self.assertIsNone(self.mod.resolve_editor_by_lesson('26'))
        self.allow_write=True;self.allow_course=False
        self.assertIsNone(self.mod.resolve_editor_by_lesson('26'))
        self.allow_course=True
        self.rows['Lesson Reference'][0]['lesson']='another-lesson'
        self.assertIsNone(self.mod.resolve_editor_by_lesson('26'))
        self.rows['Lesson Reference'][0]['lesson']='lesson-a'
        self.rows['Course Lesson'][0]['course']='missing-course'
        self.assertIsNone(self.mod.resolve_editor_by_lesson('26'))

    def add_second_lesson(self):
        self.rows['Course Lesson'].append(dict(self.rows['Course Lesson'][0],name='lesson-b',custom_avo_id='27'))
        self.rows['Lesson Reference'].append(dict(self.rows['Lesson Reference'][0],lesson='lesson-b',idx=4))
        self.ordered.append({'name':'lesson-b'})

    def test_course_start_prefers_existing_resume_then_first_lesson(self):
        self.add_second_lesson()
        first=self.mod.resolve_course_start('11')
        self.assertEqual(first,{'course_name':'course-a','lesson_name':'lesson-a','chapter_number':2,
                                'lesson_number':3,'course_id':'11','lesson_id':'26'})
        self.membership={'current_lesson':'lesson-b'}
        self.assertEqual(self.mod.resolve_course_start('11')['lesson_id'],'27')
        self.resume='lesson-a';self.locked={'lesson-b'}
        self.assertEqual(self.mod.resolve_course_start('11')['lesson_id'],'26')

    def test_course_start_skips_inaccessible_missing_and_wrong_account_lessons(self):
        self.add_second_lesson();self.membership={'current_lesson':'lesson-outside'}
        self.assertEqual(self.mod.resolve_course_start('11')['lesson_id'],'26')
        self.locked={'lesson-a'}
        self.assertEqual(self.mod.resolve_course_start('11')['lesson_id'],'27')
        self.locked=set();self.rows['Course Lesson'][0]['custom_avo_account']='iomp'
        self.assertEqual(self.mod.resolve_course_start('11')['lesson_id'],'27')
        self.rows['Course Lesson'][1]['custom_avo_id']=None
        self.assertIsNone(self.mod.resolve_course_start('11'))

    def test_course_start_refuses_denied_or_ambiguous_courses(self):
        self.allow_course=False
        self.assertIsNone(self.mod.resolve_course_start('11'))
        self.allow_course=True;self.allow_lesson=False
        self.assertIsNone(self.mod.resolve_course_start('11'))
        self.allow_lesson=True;self.locked={'lesson-a'}
        self.assertIsNone(self.mod.resolve_course_start('11'))
        self.locked=set();self.rows['LMS Course'].append(dict(self.rows['LMS Course'][0],name='duplicate-course'))
        self.assertIsNone(self.mod.resolve_course_start('11'))
        self.rows['LMS Course'].pop();self.frappe.local.site='my-lk.iomp.ru'
        self.assertIsNone(self.mod.resolve_course_start('11'))

    def test_course_start_falls_back_in_course_order_when_resume_is_not_permitted(self):
        self.add_second_lesson();self.membership={'current_lesson':'lesson-a'}
        sys.modules['lms.lms.permissions'].can_access_lesson=lambda name:name != 'lesson-a'
        self.assertEqual(self.mod.resolve_course_start('11')['lesson_id'],'27')
        self.ordered=[]
        self.assertIsNone(self.mod.resolve_course_start('11'))

    def test_source_editor_saves_only_original_document_and_allowed_fields(self):
        data=self.mod.get_editor_by_source('11','26')
        self.assertEqual(data['lesson']['name'],'lesson-a')
        with self.assertRaises(PermissionError):self.mod.save_editor_by_source('11','26','other',{'title':'Edited'})
        with self.assertRaises(ValueError):self.mod.save_editor_by_source('11','26','lesson-a',{'course':'other'})
        self.assertEqual(self.saved,[])
        self.assertEqual(self.mod.save_editor_by_source('11','26','lesson-a',{'title':'Edited'}),{'saved':True})
        self.assertEqual(self.saved,['lesson-a'])
        self.rows['Course Lesson'][0]['custom_avo_id']='27'
        with self.assertRaises(PermissionError):self.mod.save_editor_by_source('11','26','lesson-a',{'title':'Wrong'})
        self.assertEqual(self.saved,['lesson-a'])
        self.rows['LMS Course'].pop();self.frappe.local.site='my-lk.iomp.ru'
        self.assertNotIn('avo_course_id',self.mod.annotate_course_ids([{'name':'course-a'}])[0])

    def test_editor_rechecks_identity_after_lookup_and_before_save(self):
        original=self.frappe.db.get_value
        def swapped(doctype, name, fields, as_dict=False):
            result=original(doctype, name, fields, as_dict)
            if doctype == 'Course Lesson' and isinstance(fields,list) and 'body' in fields:
                result['custom_avo_id']='27'
            return result
        self.frappe.db.get_value=swapped
        with self.assertRaises(PermissionError):self.mod.get_editor_by_source('11','26')
        self.frappe.db.get_value=original
        def change_mapping(*args):self.rows['Course Lesson'][0]['custom_avo_id']='27'
        self.frappe.db.sql=change_mapping
        with self.assertRaises(PermissionError):self.mod.save_editor_by_source('11','26','lesson-a',{'title':'Wrong'})
        self.assertEqual(self.saved,[])


if __name__=='__main__':unittest.main()

import base64
import json
import unittest
import zlib

from course_rules import ORIGIN, read_fresh_rules


class CourseRulesTests(unittest.TestCase):
    def capture(self):
        root = {'name':'page', 'children':[
            {'name':'text','fields':{'html':'<h1>Продление</h1><p>Текст</p>'}},
            {'name':'text','fields':{'html':'<p><iframe src="https://example.org/calendar"></iframe></p>'}},
            {'name':'code','fields':{'html':'<script src="https://example.org/form.js"></script>'}},
            {'name':'text','fields':{'html':'Private', 'visibleConditions':{'test':True}}},
        ]}
        block = base64.b64encode(zlib.compress(json.dumps(root).encode())).decode()
        return {'course_id':15, 'source_origin':ORIGIN, 'draft_lesson_ids':[4],
            'settings':{'start_date_used':'0','end_date':'9999-12-31 23:59:59','always_show':1,
                        'permanent_lesson_access':0,'permanent_lesson_access_days':'1'},
            'no_access_info':{'formatVersion':4,'packed':True,'block':block}}

    def test_notice_visibility_and_retention_are_independent(self):
        capture = self.capture()
        result = read_fresh_rules(capture)
        self.assertIsNone(result['starts_at'])
        self.assertEqual(result['end_at']['kind'],'unlimited')
        self.assertFalse(result['permanent_lesson_access'])
        self.assertEqual(json.loads(result['access_notice_content'])['blocks'], [
            {'type':'header', 'data':{'text':'Продление','level':1}},
            {'type':'paragraph', 'data':{'text':'Текст'}},
            {'type':'paragraph', 'data':{'text':'<a href="https://example.org/calendar">https://example.org/calendar</a>'}},
        ])
        self.assertEqual(set(result['notice_warnings']),{'omitted_script','iframe_as_link','conditional_notice_block'})
        capture['settings'].update(always_show=0, permanent_lesson_access=1, start_date_used='1',
                                   start_date='2026-01-15 13:00:00', end_date='2026-10-12 23:00:00')
        result = read_fresh_rules(capture)
        self.assertIsNone(result['access_notice_content'])
        self.assertTrue(result['permanent_lesson_access'])
        self.assertEqual(result['starts_at']['iso'],'2026-01-15T13:00:00+03:00')
        self.assertEqual(result['end_at']['iso'],'2026-10-12T23:00:00+03:00')

    def test_unknown_bound_and_wrong_course_do_not_default_to_open(self):
        capture = self.capture()
        capture['settings']['end_date'] = ''
        self.assertEqual(read_fresh_rules(capture)['end_at']['kind'],'unknown')
        with self.assertRaisesRegex(ValueError,'course_id_mismatch'):
            read_fresh_rules(capture, {'course_id':16, 'draft_lesson_ids':[]})
        capture['source_origin']='https://example.org'
        with self.assertRaisesRegex(ValueError,'wrong_course_origin'):
            read_fresh_rules(capture)


if __name__ == '__main__':
    unittest.main()

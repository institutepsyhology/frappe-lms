import importlib.util
import json
from pathlib import Path
import sys
import types
import unittest
from datetime import datetime
from unittest.mock import Mock, patch


class Row(dict):
    __getattr__ = dict.get


class PresentationTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 11, 17, 12)
        self.blocked = False
        self.grants = []
        self.values = {}
        self.author = False
        self.membership = True
        self.protected = True
        self.publication = True
        f = types.ModuleType('frappe')
        f.whitelist = lambda **kw: lambda fn: fn
        f.session = Row(user='student')
        f.get_meta = lambda dt: Row(has_field=lambda field: True)
        f.get_all = lambda dt, **kw: self.grants if dt == 'LMS Access Grant' else []
        def value(dt, name, fields, **kwargs):
            if dt == 'LMS Access Policy': return 'policy' if isinstance(fields, str) else Row()
            if dt == 'Course Lesson' and isinstance(fields, list): return Row(course='course')
            if isinstance(fields, str): return self.values.get((dt, fields))
            return None
        f.db = Row(get_value=value, set_value=Mock())
        f.ValidationError = ValueError
        f.throw = lambda msg, exc: (_ for _ in ()).throw(exc(msg))
        util = types.ModuleType('frappe.utils')
        util.get_datetime = lambda value: value if isinstance(value, datetime) else datetime.fromisoformat(value)
        util.now_datetime = lambda: self.now
        utils = types.ModuleType('lms.lms.utils')
        utils.get_membership = lambda course, member=None: self.membership
        utils.sanitize_editorjs = lambda raw: raw
        blocks = types.ModuleType('lms.lms.access_blocks')
        blocks.is_blocked = lambda *args: self.blocked
        perms = types.ModuleType('lms.lms.permissions')
        perms.can_author_course = lambda course, user=None: self.author
        perms.publication_allows_lesson = lambda *args: self.publication
        self.require = Mock()
        authority = types.ModuleType('lms.lms.staff_authority')
        authority.require_capability = self.require
        people = types.ModuleType('lms.lms.course_people')
        people._check = lambda course, action: self.require('course_access', action, course=course)
        self.patch = patch.dict(sys.modules, {'lms.lms.course_people':people,'frappe':f,'frappe.utils':util,'lms.lms.utils':utils,
            'lms.lms.access_blocks':blocks,'lms.lms.permissions':perms,'lms.lms.staff_authority':authority})
        self.patch.start()
        def load(name, filename):
            spec = importlib.util.spec_from_file_location(name,Path(__file__).with_name(filename))
            module = importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module
        individual = load('individual_presentation_test','individual_access.py')
        individual.policy_applies = lambda course: self.protected
        self.more = patch.dict(sys.modules, {'lms.lms.individual_access':individual});self.more.start()
        self.m = load('presentation_test','access_presentation.py')
        self.f = f

    def tearDown(self):
        self.more.stop();self.patch.stop()

    def grant(self, **kwargs):
        return Row(name='grant',status='Active',starts_at='2026-11-01 00:00:00',personal_end_type='Unlimited',
            personal_end_days=0,course_end_type='Unlimited',ignore_course_end=0,**kwargs)

    def test_course_deny_precedes_active_grant(self):
        self.grants = [self.grant()];self.blocked = True
        self.assertEqual(self.m.course_state('course')['status'],'Blocked')
        self.blocked = False
        self.assertTrue(self.m.course_state('course')['available'])

    def test_an_active_grant_wins_over_future_and_expired(self):
        future = self.grant();future['starts_at']='2026-12-01 00:00:00'
        expired = self.grant();expired.update(personal_end_type='At',ends_at='2026-11-10 10:00:00')
        self.grants = [future,expired,self.grant()]
        self.assertEqual(self.m.course_state('course')['status'],'Active')
        self.grants = [future,expired]
        state = self.m.course_state('course')
        self.assertEqual(state['status'],'Scheduled')
        self.assertIn('01.12.2026 00:00',state['message'])
        self.grants = [expired]
        self.assertEqual(self.m.course_state('course')['status'],'Expired')

    def test_missing_rules_do_not_invent_an_opening(self):
        unknown = self.grant();unknown['personal_end_type']='Unknown'
        self.grants = [unknown]
        self.assertFalse(self.m.course_state('course')['available'])
        self.assertNotIn('starts_at',self.m.course_state('course'))

    def test_notice_does_not_return_assessments_or_lesson_content(self):
        self.values[('Course Lesson','access_notice_content')] = json.dumps({'blocks':[
            {'type':'paragraph','data':{'text':'Buy access'}},
            {'type':'quiz','data':{'quiz':'SECRET'}},
            {'type':'assignment','data':{'assignment':'SECRET'}}]})
        notice = json.loads(self.m.notice_content('Course Lesson','lesson'))
        self.assertEqual([block['type'] for block in notice['blocks']],['paragraph'])
        self.assertNotIn('SECRET',json.dumps(notice))

    def test_unpublished_lesson_never_discloses_notice_or_title(self):
        self.publication = False
        self.values[('Course Lesson','title')] = 'SECRET TITLE'
        payload = self.m.lesson_notice('course','lesson')
        self.assertTrue(payload['not_found'])
        self.assertNotIn('SECRET',json.dumps(payload))
        self.assertNotIn('content',payload)

    def test_available_lesson_keeps_its_known_opening_date(self):
        self.grants = [self.grant()]
        self.values[('LMS Course','enforce_lesson_completion')] = 0
        perms = sys.modules['lms.lms.permissions']
        perms.can_access_lesson = lambda lesson, user=None: True
        with patch.object(self.m, '_assigned_rule', return_value=Row(opening_type='After Start',delay_days=2)):
            state = self.m.lesson_state('course','lesson','student')
        self.assertTrue(state['available'])
        self.assertEqual(state['opens_at'],'2026-11-03 00:00:00')

    def test_expired_course_with_retained_lesson_stays_visible(self):
        self.values[('LMS Course','show_when_unavailable')] = 0
        expired = self.grant();expired.update(personal_end_type='At',ends_at='2026-11-10 10:00:00')
        self.grants = [expired]
        original = self.f.get_all
        self.f.get_all = lambda kind, **kw: ['lesson'] if kind == 'LMS Access Grant Lesson' else original(kind,**kw)
        with patch.object(sys.modules['lms.lms.individual_access'],'grant_allows_lesson',return_value=True):
            state = self.m.course_notice('course')
        self.assertTrue(state['visible'])
        self.assertTrue(state['retained_access'])
        self.assertEqual(state['status'],'Expired')

    def test_hidden_courses_are_filtered_before_pagination_and_keep_existing_filters(self):
        self.f.get_all = lambda kind, **kw: ['hidden-course'] if kind == 'LMS Course' else []
        sys.modules['lms.lms.utils'].as_filter_conditions = lambda values: [[k,'=',v] for k,v in values.items()]
        with patch.object(self.m,'course_notice',return_value={'visible':False}):
            filters = self.m.visible_course_filters({'published':1})
        self.assertEqual(filters,[['published','=',1],['name','not in',['hidden-course']]])

    def test_staff_edit_requires_authority_before_write(self):
        self.require.side_effect=PermissionError
        with self.assertRaises(PermissionError):
            self.m.save_visibility_settings('course',1)
        self.f.db.set_value.assert_not_called()
        self.assertEqual(self.f.session.user,'student')


if __name__ == '__main__': unittest.main()

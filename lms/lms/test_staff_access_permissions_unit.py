import importlib.util
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import patch


class Row(dict):
    __getattr__ = dict.get
    def is_new(self):return not bool(self.get('name'))


class PermissionTests(unittest.TestCase):
    def setUp(self):
        f=types.ModuleType('frappe');f.session=Row(user='staff')
        f.db=Row(get_value=lambda *a,**kw:Row(course='course-a',member='learner'),escape=lambda v:"'"+v.replace("'","''")+"'")
        self.f=f
        self.allowed=True;self.position={'active':True,'permissions':{('course_access','read')},'scope':'Owned'}
        policy=types.ModuleType('lms.lms.staff_policy')
        policy.assigned_capability=lambda *a,**kw:self.allowed
        policy.assigned_position=lambda *a,**kw:self.position
        authority=types.ModuleType('lms.lms.staff_authority')
        authority.user_delete_permission=lambda *a,**kw:False if kw.get('ptype')=='delete' else None
        self.patch=patch.dict(sys.modules,{'frappe':f,'lms.lms.staff_policy':policy,'lms.lms.staff_authority':authority});self.patch.start()
        spec=importlib.util.spec_from_file_location('native_staff_guard',Path(__file__).with_name('staff_access_permissions.py'))
        self.m=importlib.util.module_from_spec(spec);spec.loader.exec_module(self.m)

    def tearDown(self):self.patch.stop()

    def test_explicit_deny_cannot_be_bypassed_by_native_moderator_grant(self):
        self.allowed=False
        self.assertFalse(self.m.has_permission(Row(doctype='LMS Access Grant',name='g',course='course-a'),ptype='write'))

    def test_denied_contacts_native_queries_and_document_reads_preserve_self_only(self):
        self.allowed=False
        self.assertEqual(self.m.user_query_conditions(),"`tabUser`.name='staff'")
        self.assertEqual(self.m.contact_query_conditions(),"`tabContact`.user='staff'")
        self.assertFalse(self.m.contact_document_permission(Row(doctype='User',name='learner')))
        self.assertFalse(self.m.contact_document_permission(Row(doctype='Contact',name='c',user='learner')))
        self.assertIsNone(self.m.contact_document_permission(Row(doctype='User',name='staff')))
        self.assertIsNone(self.m.contact_document_permission(Row(doctype='Contact',name='c',user='staff')))
        self.allowed=True
        self.assertEqual(self.m.user_query_conditions(),'')

    def test_user_delete_guard_is_not_lost_in_contact_privacy_hook(self):
        self.assertFalse(self.m.contact_document_permission(Row(doctype='User',name='learner'),ptype='delete'))

    def test_grant_changes_still_need_native_permission_after_capability_passes(self):
        self.assertIsNone(self.m.has_permission(Row(doctype='LMS Access Grant',name='g',course='course-a'),ptype='write'))

    def test_student_own_progress_and_read_not_replaced_by_staff_policy(self):
        self.allowed=False;self.f.session.user='learner'
        doc=Row(doctype='LMS Enrollment',name='e',member='learner',course='course-a')
        self.assertIsNone(self.m.has_permission(doc,ptype='write'))
        self.assertIsNone(self.m.has_permission(doc,ptype='read'))
        self.assertFalse(self.m.has_permission(doc,ptype='delete'))

    def test_relabelling_course_does_not_use_own_progress_exception(self):
        self.allowed=False;self.f.session.user='learner'
        doc=Row(doctype='LMS Enrollment',name='e',member='learner',course='other-course')
        self.assertFalse(self.m.has_permission(doc,ptype='write'))

    def test_list_is_restricted_to_owner_courses_or_own_enrollment(self):
        condition=self.m.enrollment_query_conditions()
        self.assertIn('tabCourse Instructor',condition)
        self.assertIn("member='staff'",condition)
        self.position['scope']='All'
        self.assertEqual(self.m.enrollment_query_conditions(),'')
        self.position['active']=False
        self.assertEqual(self.m.enrollment_query_conditions(),"`tabLMS Enrollment`.member='staff'")


if __name__=='__main__':unittest.main()

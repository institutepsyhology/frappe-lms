import importlib.util
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import Mock, patch


class Row(dict):
    __getattr__ = dict.get
    __setattr__ = dict.__setitem__


class CoursePeopleTests(unittest.TestCase):
    def setUp(self):
        self.fr = types.ModuleType('frappe')
        self.fr._ = lambda s: s
        self.fr.whitelist = lambda *a, **kw: lambda f: f
        self.fr.PermissionError = PermissionError
        self.fr.ValidationError = ValueError
        self.fr.throw = lambda msg, exc=ValueError: (_ for _ in ()).throw(exc(msg))
        self.fr.local = Row(site='my-lk.mv-centr.ru')
        self.fr.conf = Row(individual_access_release_enabled=True)
        self.fr.get_meta = lambda _: Row(has_field=lambda f: True)
        self.fr.get_all = Mock(return_value=[])
        self.fr.db = Row(exists=Mock(return_value=True),get_value=Mock(return_value=None),sql=Mock())
        self.require = Mock()
        self.can_read_contacts = True
        authority = types.ModuleType('lms.lms.staff_authority')
        authority.require_capability=self.require
        authority.has_capability=lambda resource,action,course=None: self.can_read_contacts if resource=='contacts' else True
        perms=types.ModuleType('lms.lms.permissions');perms.can_author_course=Mock(return_value=True)
        self.perms=perms
        utils=types.ModuleType('frappe.utils');utils.get_system_timezone=lambda:'Europe/Moscow'
        card=types.ModuleType('lms.lms.avo_contact_card');card.SITE_ACCOUNTS={'my-lk.mv-centr.ru':'mv-centr'}
        self.modpatch=patch.dict(sys.modules,{'frappe':self.fr,'frappe.utils':utils,
            'lms.lms.staff_authority':authority,'lms.lms.permissions':perms,'lms.lms.avo_contact_card':card})
        self.modpatch.start()
        spec=importlib.util.spec_from_file_location('course_people_unit',Path(__file__).with_name('course_people.py'))
        self.mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(self.mod)
        self.row=Row(enrollment='opaque-enrollment',member='student@example.test',full_name='Student',
                     email='actual@example.test',phone='123',avo_id='123',starts_at=None,ends_at=None)
        self.fr.db.sql.side_effect=lambda query,params,**kw: [[3001]] if query.startswith('SELECT COUNT(*)') else [Row(self.row)]

    def tearDown(self):
        self.modpatch.stop()

    def test_default_is_bounded_fifty_with_total_over_two_thousand(self):
        result=self.mod.list_students('course')
        self.assertEqual((result['total'],result['page_length'],result['page']),(3001,50,1))
        self.assertEqual(len(result['rows']),1)
        self.assertEqual(self.fr.db.sql.call_count,2)
        self.assertEqual(self.fr.db.sql.call_args.args[1]['limit'],50)
        self.assertEqual(self.fr.db.sql.call_args.args[1]['offset'],0)

    def test_page_sixty_one_fetches_rows_after_three_thousand(self):
        result=self.mod.list_students('course',page=61)
        self.assertEqual(result['page'],61)
        self.assertEqual(self.fr.db.sql.call_args.args[1]['offset'],3000)
        self.assertIn('LIMIT %(limit)s OFFSET %(offset)s',self.fr.db.sql.call_args.args[0])

    def test_page_clamps_after_deletion_of_last_row(self):
        result=self.mod.list_students('course',page=99)
        self.assertEqual(result['page'],61)
        self.assertEqual(self.fr.db.sql.call_args.args[1]['offset'],3000)

    def test_invalid_and_unbounded_sizes_are_rejected_before_sql(self):
        for page,size in ((0,50),(-1,50),(True,50),(1,0),(1,5000),(1,'50;DELETE'),(1,True)):
            with self.subTest(page=page,size=size), self.assertRaises(ValueError):
                self.mod.list_students('course',page=page,page_length=size)
        self.fr.db.sql.assert_not_called()

    def test_sort_is_global_and_allowlisted(self):
        for direction in ('asc','desc'):
            self.mod.list_students('course',sort_by='email',sort_dir=direction,page_length=25)
            self.assertIn('ORDER BY email '+direction.upper()+',enrollment ASC',self.fr.db.sql.call_args.args[0])
        for key,direction in (('email; DELETE FROM User','asc'),('email','desc;delete'),([], 'asc')):
            with self.assertRaises(ValueError):self.mod.list_students('course',sort_by=key,sort_dir=direction)

    def test_search_is_bound_and_does_not_interpolate_sql(self):
        self.mod.list_students('course',search="x%' OR 1=1 --")
        query,params=self.fr.db.sql.call_args.args
        self.assertNotIn('OR 1=1',query)
        self.assertIn('OR 1=1',params['term'])

    def test_course_scope_and_capability_are_checked_before_data(self):
        self.require.side_effect=PermissionError
        with self.assertRaises(PermissionError):self.mod.list_students('course')
        self.require.assert_called_with('course_access','read',course='course')
        self.fr.db.sql.assert_not_called()

    def test_cross_account_course_is_denied(self):
        self.fr.db.get_value.return_value='another-account'
        with self.assertRaises(PermissionError):self.mod.list_students('course')
        self.fr.db.sql.assert_not_called()

    def test_contact_fields_are_masked_and_not_searchable_or_sortable(self):
        self.can_read_contacts=False
        result=self.mod.list_students('course',search='student')
        self.assertEqual((result['rows'][0]['email'],result['rows'][0]['phone'],result['rows'][0]['avo_id']),('','',None))
        self.assertIsNone(result['rows'][0]['member'])
        self.assertEqual(len(result['rows'][0]['enrollment']),64)
        self.assertNotIn('OR email LIKE',self.fr.db.sql.call_args.args[0])
        with self.assertRaises(PermissionError):self.mod.list_students('course',sort_by='email')

    def test_full_name_that_contains_email_is_not_a_masking_bypass(self):
        self.can_read_contacts=False
        self.row.full_name='student@example.test'
        result=self.mod.list_students('course')
        self.assertTrue(result['rows'][0]['full_name'].startswith('Ученик '))
        self.assertNotIn('@',str(result['rows']))

    def test_opaque_enrollment_resolves_under_exact_course_and_reconciles_member(self):
        token=self.mod._enrollment_token('old-enrollment')
        self.fr.db.sql.side_effect=lambda *a,**kw:[Row(member='student')]
        self.assertEqual(self.mod._resolve_enrollment('course',token),'student')
        query,params=self.fr.db.sql.call_args.args
        self.assertIn('course=%s',query);self.assertEqual(params,('course',token))
        with self.assertRaises(ValueError):self.mod._resolve_enrollment('course',token,'someone-else')
        with self.assertRaises(ValueError):self.mod._resolve_enrollment('course','student@example.test')

    def test_provenance_does_not_invent_original_issuer(self):
        archived={'kind':'avo_import','label':'Перенос из АВО','actor':None,'issued_at':None,'snapshot_at':'2026-01-01'}
        self.assertEqual(self.mod.grant_source(Row(owner='Administrator',creation='now'),archived),archived)
        source=self.mod.grant_source(Row(access_source='Manual',issued_by='actual-staff',issued_at='2026-02-01'))
        self.assertEqual((source['kind'],source['actor'],source['issued_at']),('manual','actual-staff','2026-02-01'))

    def test_lesson_page_rejects_grant_for_a_different_pair(self):
        self.fr.db.exists.side_effect=lambda doctype,*a,**kw: doctype!='LMS Access Grant'
        with self.assertRaises(ValueError):self.mod.list_member_lessons('course','student','foreign-grant')
        self.fr.db.sql.assert_not_called()

    def test_remove_closes_all_grants_then_removes_only_enrollment(self):
        self.fr.db.get_value.side_effect=lambda doctype,*a,**kw: 'opaque-enrollment' if doctype=='LMS Enrollment' else None
        self.fr.db.exists.side_effect=lambda doctype,*a,**kw:doctype!='DocType'
        self.fr.get_all.return_value=['grant-b','grant-a']
        grants={n:Row(name=n,course='course',member='student',status='Active',frozen_at='old',flags=Row(),save=Mock(),add_comment=Mock()) for n in ('grant-a','grant-b')}
        self.fr.get_doc=lambda doctype,name,**kw:grants[name]
        self.fr.delete_doc=Mock()
        result=self.mod.remove_student('course','student')
        self.assertEqual(result,{'removed':True,'grants_closed':2,'learning_records_preserved':True})
        for grant in grants.values():
            self.assertEqual(grant.status,'Revoked');self.assertIsNone(grant.frozen_at);grant.save.assert_called_once()
        self.fr.delete_doc.assert_called_once_with('LMS Enrollment','opaque-enrollment',ignore_permissions=True)

    def test_imported_enrollment_clears_only_derived_mapping_and_retains_source(self):
        self.fr.db.get_value.side_effect=lambda doctype,*a,**kw:'enrollment' if doctype=='LMS Enrollment' else None
        self.fr.db.set_value=Mock()
        ledger=Row(name='archive',mapped_course='course',mapped_user='student',account='mv-centr',grant='grant',
                   enrollment='enrollment',source_payload='immutable source',source_snapshot_hash='immutable hash',captured_at='old',add_comment=Mock())
        grant=Row(name='grant',course='course',member='student',status='Frozen',frozen_at='old',flags=Row(),save=Mock(),add_comment=Mock())
        self.fr.get_all.side_effect=lambda doctype,**kw:['archive'] if doctype=='AVO Course Access' else ['grant']
        self.fr.get_doc=lambda doctype,name,**kw:ledger if doctype=='AVO Course Access' else grant
        self.fr.delete_doc=Mock()
        self.mod.remove_student('course','student')
        self.fr.db.set_value.assert_called_once_with('AVO Course Access','archive',{'enrollment':None,'sync_status':'Needs Review','review_reason':'staff_removed_enrollment'})
        self.assertEqual((ledger.source_payload,ledger.source_snapshot_hash,ledger.captured_at,ledger.grant),('immutable source','immutable hash','old','grant'))
        self.assertEqual(grant.status,'Revoked')
        grant.add_comment.assert_called_once();ledger.add_comment.assert_called_once()

    def test_foreign_archive_mapping_stops_before_any_write(self):
        self.fr.db.get_value.side_effect=lambda doctype,*a,**kw:'enrollment' if doctype=='LMS Enrollment' else None
        ledger=Row(name='archive',mapped_course='other',mapped_user='student',account='mv-centr',grant='grant',enrollment='enrollment')
        self.fr.get_all.side_effect=lambda doctype,**kw:['archive'] if doctype=='AVO Course Access' else ['grant']
        self.fr.get_doc=Mock(return_value=ledger);self.fr.delete_doc=Mock();self.fr.db.set_value=Mock()
        with self.assertRaises(ValueError):self.mod.remove_student('course','student')
        self.fr.delete_doc.assert_not_called();self.fr.db.set_value.assert_not_called()


if __name__=='__main__':unittest.main()

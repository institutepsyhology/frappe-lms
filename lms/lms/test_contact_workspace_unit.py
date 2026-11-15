import importlib.util
import json
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch


class Row(dict):
    __getattr__ = dict.get
    def __setattr__(self, key, value): self[key] = value


class Doc(Row):
    @property
    def flags(self):
        return self.setdefault('_flags', Row())
    def set(self, field, value): self[field] = value
    def append(self, field, value): self.setdefault(field, []).append(Row(value))
    def save(self, **kwargs): self.saved = True
    def insert(self, **kwargs): self.name = kwargs['set_name']; self.insert_options = kwargs; return self


class WorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.allow = {('contacts', 'read'), ('contacts', 'write'), ('contacts', 'create')}
        self.credentials = False
        self.roles = []
        self.rows = {}
        self.queries = []
        self.docs = {}
        self.created = []
        f = types.ModuleType('frappe')
        f._ = lambda value: value
        f.whitelist = lambda *a, **kw: lambda func: func
        f.ValidationError = ValueError
        f.PermissionError = PermissionError
        f.throw = lambda message, exc=ValueError: (_ for _ in ()).throw(exc(message))
        f.local = Row(site='my-lk.mv-centr.ru')
        f.session = Row(user='viewer@example.test')
        f.get_roles = lambda *a: self.roles
        f.get_meta = lambda kind: Row(has_field=lambda field: True)
        f.parse_json = json.loads
        f.generate_hash = lambda **kw: 'native-identity'
        f.db = Row(exists=lambda *a, **kw: bool(self.rows.get('AVO Course Access')))
        def get_all(kind, **kwargs):
            self.queries.append((kind, kwargs))
            return self.rows.get(kind, [])
        f.get_all = get_all
        def get_doc(value, name=None):
            if isinstance(value, dict):
                doc = Doc(value);self.created.append(doc);return doc
            return self.docs[(value, name)]
        f.get_doc = get_doc
        self.f = f
        legacy = types.ModuleType('lms.lms.avo_contact_card')
        legacy.SITE_ACCOUNTS = {'my-lk.mv-centr.ru': 'mv-centr'}
        legacy.EDITABLE = ('first_name', 'middle_name', 'last_name', 'mobile_no', 'custom_avo_telegram_username', 'custom_avo_telegram_id', 'custom_avo_vk_username', 'custom_avo_vk_id')
        legacy.SOCIAL_FIELDS = tuple(field for field in legacy.EDITABLE if field.startswith('custom_avo_'))
        legacy._document = lambda kind, name: self.docs[(kind, name)]
        legacy._present = lambda doc: {key: doc.get(key) for key in ('name', 'email', 'custom_avo_contact_id', 'custom_avo_account')} | {'kind': doc.doctype}
        authority = types.ModuleType('lms.lms.staff_authority')
        authority.has_capability = lambda resource, action, course=None: (resource, action) in self.allow or (resource, action, course) in self.allow
        def require(resource, action, course=None):
            if not authority.has_capability(resource, action, course): raise PermissionError('denied')
        authority.require_capability = require
        credential = types.ModuleType('lms.lms.credential_profiles')
        credential.can_manage_credentials = lambda *a: self.credentials
        support = types.ModuleType('lms.lms.support_credentials')
        support.PRIVILEGED_ROLES = {'Moderator', 'System Manager'}
        access = types.ModuleType('lms.lms.individual_access')
        access.resolve_end = lambda kind, value, days, start: (kind, value)
        people = types.ModuleType('lms.lms.course_people')
        people.grant_source = lambda grant, archived=None: ({'kind': grant['access_source'].lower(), 'label': 'Выдано сотрудником',
            'actor': grant.get('issued_by'), 'issued_at': grant.get('issued_at')} if grant.get('access_source') == 'Manual' else archived or
            {'kind': 'unknown', 'label': 'Способ выдачи не записан', 'actor': None, 'issued_at': None})
        utils = types.ModuleType('frappe.utils')
        utils.validate_email_address = lambda value, **kw: value if '@' in value else None
        self.patch = patch.dict(sys.modules, {'frappe': f, 'frappe.utils': utils,
            'lms.lms.avo_contact_card': legacy, 'lms.lms.staff_authority': authority,
            'lms.lms.credential_profiles': credential, 'lms.lms.support_credentials': support,
            'lms.lms.individual_access': access, 'lms.lms.course_people': people})
        self.patch.start()
        spec = importlib.util.spec_from_file_location('workspace_test_module', Path(__file__).with_name('contact_workspace.py'))
        self.m = importlib.util.module_from_spec(spec);spec.loader.exec_module(self.m)
        self.contact = Doc(doctype='Contact', name='contact-one', first_name='', custom_avo_contact_id='42', custom_avo_account='mv-centr')
        self.user = Doc(doctype='User', name='person@example.test', user_type='Website User', custom_avo_contact_id='42', custom_avo_account='mv-centr')
        self.docs[('Contact', self.contact.name)] = self.contact
        self.docs[('User', self.user.name)] = self.user

    def tearDown(self): self.patch.stop()

    def test_basic_card_permission_is_independent_of_password_permission(self):
        result = self.m.get_card('User', self.user.name)
        self.assertTrue(result['capabilities']['read'])
        self.assertTrue(result['capabilities']['write'])
        self.assertFalse(result['capabilities']['credential_read'])
        self.allow.add(('credentials', 'read'))
        self.assertTrue(self.m.get_card('User', self.user.name)['capabilities']['credential_read'])
        self.assertFalse(self.m.get_card('User', self.user.name)['capabilities']['credential_send'])
        self.assertFalse(self.m.get_card('User', self.user.name)['capabilities']['credential_write'])
        self.assertFalse(self.m.get_card('Contact', self.contact.name)['capabilities']['credential_read'])
        self.user.user_type = 'System User'
        self.assertFalse(self.m.get_card('User', self.user.name)['capabilities']['credential_read'])

    def test_site_and_linked_identity_fail_closed(self):
        self.contact.custom_avo_account = 'mastervision'
        with self.assertRaises(PermissionError): self.m.get_card('Contact', self.contact.name)
        self.contact.custom_avo_account = 'mv-centr';self.contact.user = self.user.name
        self.assertEqual(self.m.get_card('Contact', self.contact.name)['kind'], 'User')
        self.user.custom_avo_contact_id = '43'
        with self.assertRaises(ValueError): self.m.get_card('Contact', self.contact.name)

    def test_contact_writer_cannot_edit_staff_or_smuggle_roles(self):
        self.user.user_type = 'System User'
        with self.assertRaises(PermissionError): self.m.save_card('User', self.user.name, {'first_name': 'Updated'})
        self.user.user_type = 'Website User'
        with self.assertRaises(ValueError): self.m.save_card('User', self.user.name, {'roles': ['System Manager']})
        self.allow.remove(('contacts', 'write'))
        with self.assertRaises(PermissionError): self.m.save_card('Contact', self.contact.name, {'first_name': 'Updated'})

    def test_create_social_only_contact_without_creating_login_or_fake_email(self):
        result = self.m.create_contact({'custom_avo_telegram_id': '123456'})
        self.assertEqual(result['kind'], 'Contact')
        self.assertEqual(len(self.created), 1)
        self.assertEqual(self.created[0].doctype, 'Contact')
        self.assertFalse(self.created[0].get('first_name'))
        self.assertFalse(self.created[0].get('email_ids'))
        self.assertTrue(self.created[0].insert_options['ignore_mandatory'])
        for values in ({}, {'roles': []}, {'email': 'bad-email'}):
            with self.assertRaises(ValueError): self.m.create_contact(values)

    def test_sort_and_pagination_validate_before_query_and_filter_hidden_courses(self):
        for options in ((0, 50, 'title', 'asc'), (True, 50, 'title', 'asc'), (1.5, 50, 'title', 'asc'), (1, 201, 'title', 'asc'), (1, 50, 'title desc;delete', 'asc')):
            with self.assertRaises(ValueError): self.m._page_options(*options)
        self.allow.add(('course_access', 'read', 'course-one'))
        self.rows['LMS Enrollment'] = [Row(name='e', course='course-one', creation='2026-01-01', owner='staff'), Row(name='e2', course='hidden', creation='2026-02-01')]
        self.rows['LMS Course'] = [Row(name='course-one', title='Course One')]
        result = self.m.list_person_courses('User', self.user.name)
        self.assertEqual(result['total'], 1)
        self.assertEqual(result['page_size'], 50)
        self.assertEqual(result['rows'][0]['source_type'], 'unknown')
        self.assertIsNone(result['rows'][0]['source_actor'])
        self.assertEqual(self.queries[0][1]['filters'], {'member': self.user.name})

    def test_archive_contact_courses_use_newest_source_relation_without_invented_actor(self):
        self.allow.add(('course_access', 'read', 'course-one'))
        self.rows['AVO Course Access'] = [Row(source_access_id=str(i), source_course_id='10', mapped_course='course-one', sync_status='Stored',
            source_payload=json.dumps({'access': {'opens_at': f'2026-01-{i:02} 10:00:00'}}), creation='2026-11-12', owner='Importer') for i in (1, 2)]
        self.rows['LMS Course'] = [Row(name='course-one', title='Course One')]
        result = self.m.list_person_courses('Contact', self.contact.name)
        row = result['rows'][0]
        self.assertEqual(row['starts_at'], '2026-01-02 10:00:00')
        self.assertEqual(row['source_label'], 'Перенос из АВО')
        self.assertIsNone(row['source_actor'])
        self.assertIsNone(row['source_event_at'])
        self.assertEqual(row['imported_by'], 'Importer')
        self.assertTrue(row['archive_only'])
        self.assertFalse(row['can_edit'])
        ledger_query = next(query for kind, query in self.queries if kind == 'AVO Course Access')
        self.assertEqual(ledger_query['filters'], {'account': 'mv-centr', 'source_contact_id': '42'})

    def test_explicit_new_issuance_has_its_actual_actor_and_time(self):
        self.allow.add(('course_access', 'read', 'course-one'))
        self.rows['LMS Access Grant'] = [Row(name='g', course='course-one', status='Active', creation='2026-11-15',
            access_source='Manual', issued_by='staff@example.test', issued_at='2026-11-15 09:00:00',
            starts_at='2026-11-16', personal_end_type='Unlimited', course_end_type='Unlimited')]
        self.rows['LMS Course'] = [Row(name='course-one', title='Course One')]
        row = self.m.list_person_courses('User', self.user.name)['rows'][0]
        self.assertEqual(row['source_type'], 'manual')
        self.assertEqual(row['source_actor'], 'staff@example.test')
        self.assertEqual(row['source_event_at'], '2026-11-15 09:00:00')

    def test_people_list_parameters_and_sort_are_bounded(self):
        calls = []
        def query(sql, params, **kwargs):
            calls.append((sql, params))
            return [[120]] if sql.startswith('SELECT COUNT') else [Row(kind='Contact',name='c',full_name='Contact')]
        self.f.db.sql = query
        result = self.m.list_people(page=2, page_size=50, search='A_%', sort='email', direction='desc')
        self.assertEqual(result['total'], 120)
        self.assertEqual(calls[-1][1][-2:], [50, 50])
        self.assertIn('ORDER BY p.email DESC', calls[-1][0])
        self.assertNotIn('A_%', calls[-1][0])
        self.assertIn('NOT EXISTS', calls[-1][0])
        with self.assertRaises(ValueError): self.m.list_people(sort='name;DELETE')

    def test_source_resolver_requires_card_read_and_scopes_both_kinds(self):
        self.rows['User'] = [Row(name=self.user.name)]
        self.assertEqual(self.m.resolve_source_id('42')['kind'], 'User')
        self.rows['Contact'] = [Row(name=self.contact.name, user=self.user.name)]
        self.assertEqual(self.m.resolve_source_id('42')['name'], self.user.name)
        self.rows['Contact'][0].user = None
        with self.assertRaises(ValueError): self.m.resolve_source_id('42')
        for value in ('0','１２','../42'):
            with self.assertRaises(ValueError): self.m.resolve_source_id(value)
        self.allow.remove(('contacts', 'read'))
        with self.assertRaises(PermissionError): self.m.resolve_source_id('42')


if __name__ == '__main__': unittest.main()

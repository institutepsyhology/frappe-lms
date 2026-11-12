import copy
from datetime import datetime
import hashlib
import json
import sqlite3
import unittest
from types import SimpleNamespace

import enable_imported_access as operator


class Row(dict):
    __getattr__ = dict.get


class Doc(Row):
    def __init__(self, app, values):
        super().__init__(copy.deepcopy(values))
        object.__setattr__(self, 'app', app)
        object.__setattr__(self, 'flags', SimpleNamespace())

    def save(self):
        if self['doctype'] == 'Course Lesson':
            if self.get('is_draft') == 0 and not getattr(self.flags, 'lesson_publication_action', False):
                raise RuntimeError('publication action required')
            if self.app.corrupt_content:
                self['content'] += ' changed'
        self.app.tables[self['doctype']][self['name']] = copy.deepcopy(dict(self))


class Fake:
    def __init__(self):
        self.local = SimpleNamespace(site=operator.target.SITE)
        self.session = SimpleNamespace(user='Administrator')
        self.conf = {'individual_access_release_enabled': True}
        self.utils = SimpleNamespace(now_datetime=lambda: datetime(2026, 11, 12, 18, 0, 0, 123456))
        self.db = self
        self.timezone = 'Europe/Moscow'
        self.invalid_parent = self.invalid_child = 0
        self.corrupt_content = False
        self.grants = [{'name': 'owned-grant', 'lessons': ['lesson-1'], 'member': 'private-user'}]
        self.enrollments = [{'name': 'owned-enrollment', 'progress': 42}]
        self.tables = {
            'LMS Course': {'course-1': {'doctype': 'LMS Course', 'name': 'course-1',
                'custom_avo_account': 'mv-centr', 'custom_avo_id': '101', 'custom_lms_id': '101',
                'published': 0, 'disable_self_learning': 0, 'title': 'Course <b>title</b>',
                'description': '<p>Description</p>', 'short_introduction': 'Intro'}},
            'Course Lesson': {name: {'doctype': 'Course Lesson', 'name': name,
                'custom_avo_account': 'mv-centr', 'custom_avo_id': str(index), 'custom_lms_id': str(index),
                'course': 'course-1', 'chapter': 'chapter-1', 'is_draft': 1,
                'publication_audience': None, 'lesson_published_at': None, 'include_in_preview': 0,
                'title': '<b>Lesson</b>', 'content': '{"blocks":[{"type":"text"}]}',
                'body': '', 'instructor_content': ''}
                for name, index in (('lesson-1', 1), ('lesson-unassigned', 2))},
            'LMS Access Policy': {'avo-mv-centr-policy-101': {'doctype': 'LMS Access Policy',
                'name': 'avo-mv-centr-policy-101', 'course': 'course-1',
                **copy.deepcopy(operator.activation.POLICY_VALUES)}}}
        self.snapshot = None
        self.commits = self.rollbacks = 0

    def begin(self): self.snapshot = copy.deepcopy(self.tables)
    def commit(self): self.commits += 1; self.snapshot = None
    def rollback(self):
        self.rollbacks += 1
        if self.snapshot is not None: self.tables = self.snapshot
        self.snapshot = None
    def get_single_value(self, doctype, field): return self.timezone
    def get_all(self, doctype, filters=None, fields=None, limit_page_length=0):
        rows = [row for row in self.tables[doctype].values()
                if all(row.get(key) == value for key, value in (filters or {}).items())]
        return [Row({key: row.get(key) for key in fields}) for row in rows]
    def get_doc(self, doctype, name, **kwargs): return Doc(self, self.tables[doctype][name])
    def sql(self, query, parameters=None, as_dict=False):
        if query == operator.BAD_PARENT_SQL: return [{'n': self.invalid_parent}]
        if query == operator.BAD_CHILD_SQL: return [{'n': self.invalid_child}]
        if query == operator.CANDIDATE_SQL:
            names = {name for grant in self.grants for name in grant['lessons']}
            fields = ('name', 'course', 'custom_avo_id', 'custom_avo_account', 'is_draft',
                      'publication_audience', 'lesson_published_at', 'include_in_preview')
            return [Row({key: self.tables['Course Lesson'][name][key] for key in fields})
                    for name in names]
        if query == operator.SIGNATURE_SQL:
            digest = lambda value: hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()
            return [{'grants': len(self.grants), 'enrollments': len(self.enrollments),
                     'enrollment_crc': digest([{key: row.get(key) for key in
                         ('name', 'member', 'course', 'role', 'member_type')} for row in self.enrollments]),
                     'lesson_rows': sum(len(grant['lessons']) for grant in self.grants),
                     'lesson_crc': digest([grant['lessons'] for grant in self.grants]),
                     'grant_crc': digest(self.grants)}]
        raise AssertionError('unexpected query')


class ImportedAccessTest(unittest.TestCase):
    def setUp(self): self.fr, self.journal = Fake(), []
    def apply(self, **kwargs): return operator.apply(self.fr, self.journal.append, **kwargs)

    def test_dry_plan_does_not_change_data_and_only_selects_granted_lesson(self):
        before = copy.deepcopy(self.fr.tables)
        result = operator.plan(self.fr)
        self.assertEqual(self.fr.tables, before)
        self.assertEqual([row['name'] for row in result['lessons']], ['lesson-1'])
        self.assertEqual(result['summary']['lessons_to_enable'], 1)
        self.assertEqual(self.fr.commits, 0)

    def test_enables_only_assigned_staging_lesson_without_broadening_grants(self):
        grants, enrollments = copy.deepcopy(self.fr.grants), copy.deepcopy(self.fr.enrollments)
        before = copy.deepcopy(self.fr.tables)
        result = self.apply()
        lesson = self.fr.tables['Course Lesson']['lesson-1']
        self.assertEqual((lesson['is_draft'], lesson['publication_audience'], lesson['include_in_preview']),
                         (0, 'All', 0))
        self.assertEqual(lesson['lesson_published_at'], self.fr.utils.now_datetime())
        self.assertEqual(self.fr.tables['Course Lesson']['lesson-unassigned']['is_draft'], 1)
        course = self.fr.tables['LMS Course']['course-1']
        self.assertEqual((course['published'], course['disable_self_learning']), (0, 1))
        for key in operator.LESSON_FIXED:
            self.assertEqual(lesson.get(key), before['Course Lesson']['lesson-1'].get(key))
        self.assertEqual(self.fr.grants, grants); self.assertEqual(self.fr.enrollments, enrollments)
        self.assertTrue(result['personal_access_unchanged'])
        self.assertEqual(result['changed_lessons'], 1)
        self.assertNotIn('private-user', json.dumps(self.journal, default=str))
        self.assertNotIn('<b>Lesson', json.dumps(self.journal, default=str))

    def test_repeat_is_noop(self):
        self.apply(); before = copy.deepcopy(self.fr.tables)
        result = self.apply()
        self.assertEqual((result['changed_courses'], result['changed_lessons']), (0, 0))
        self.assertEqual(self.fr.tables, before)

    def test_independent_learning_progress_does_not_look_like_assignment_mutation(self):
        def student_activity(value):
            self.journal.append(value)
            if value['event'] == 'committed':
                self.fr.enrollments[0]['progress'] += 1
        result = operator.apply(self.fr, student_activity)
        self.assertTrue(result['personal_access_unchanged'])
        self.assertGreater(self.fr.enrollments[0]['progress'], 42)

    def test_site_role_flag_and_timezone_guards_prevent_writes(self):
        for key, value in [('site', 'my-lk.iomp.ru'), ('user', 'Staff'), ('release', False),
                           ('timezone', 'UTC')]:
            with self.subTest(key=key):
                self.fr = Fake()
                if key == 'site': self.fr.local.site = value
                if key == 'user': self.fr.session.user = value
                if key == 'release': self.fr.conf['individual_access_release_enabled'] = value
                if key == 'timezone': self.fr.timezone = value
                with self.assertRaises(operator.target.Rejected): self.apply()
                self.assertEqual(self.fr.commits, 0)

    def test_bad_parent_or_lesson_references_fail_closed(self):
        for key in ('invalid_parent', 'invalid_child'):
            with self.subTest(key=key):
                self.fr = Fake(); setattr(self.fr, key, 1)
                with self.assertRaisesRegex(operator.target.Rejected, 'invalid_owned_access_reference'):
                    self.apply()
                self.assertEqual(self.fr.commits, 0)

    def test_changed_course_source_or_publication_and_policy_are_rejected(self):
        variants = [('course', 'published', 1), ('course', 'custom_avo_id', 'bad-id'),
                    ('policy', 'enabled', 0), ('policy', 'lessons', [{'always_open': 1}])]
        for kind, field, value in variants:
            with self.subTest(kind=kind, field=field):
                self.fr = Fake()
                table, name = ('LMS Course', 'course-1') if kind == 'course' else ('LMS Access Policy', 'avo-mv-centr-policy-101')
                self.fr.tables[table][name][field] = value
                with self.assertRaises(operator.target.Rejected): self.apply()
                self.assertEqual(self.fr.commits, 0)

    def test_known_real_source_draft_stays_draft(self):
        result = self.apply(known_source_draft_ids={1})
        self.assertEqual(result['held_source_drafts'], 1)
        self.assertEqual(result['changed_lessons'], 0)
        self.assertEqual(self.fr.tables['Course Lesson']['lesson-1']['is_draft'], 1)

    def test_future_only_existing_publication_is_not_silently_overwritten(self):
        self.fr.tables['Course Lesson']['lesson-1'].update(is_draft=0, publication_audience='Future Only')
        with self.assertRaisesRegex(operator.target.Rejected, 'unexpected_existing_publication_audience'):
            self.apply()

    def test_content_readback_change_rolls_back_lesson(self):
        self.fr.tables['LMS Course']['course-1']['disable_self_learning'] = 1
        before = copy.deepcopy(self.fr.tables)
        self.fr.corrupt_content = True
        with self.assertRaisesRegex(operator.target.Rejected, 'publication_readback_mismatch'): self.apply()
        self.assertEqual(self.fr.tables, before)
        self.assertEqual(self.fr.commits, 0)

    def test_journal_failure_before_write_does_not_change_lesson(self):
        self.fr.tables['LMS Course']['course-1']['disable_self_learning'] = 1
        before = copy.deepcopy(self.fr.tables)
        def broken(value): raise OSError('private disk error')
        with self.assertRaises(operator.target.Rejected): operator.apply(self.fr, broken)
        self.assertEqual(self.fr.tables, before)

    def test_journal_failure_after_commit_is_explicit_unknown_outcome(self):
        self.fr.tables['LMS Course']['course-1']['disable_self_learning'] = 1
        def broken(value):
            if value['event'] == 'committed': raise OSError('private disk error')
        with self.assertRaisesRegex(operator.target.Rejected, 'journal_write_outcome_unknown'):
            operator.apply(self.fr, broken)
        self.assertEqual(self.fr.tables['Course Lesson']['lesson-1']['is_draft'], 0)

    def test_pilot_limit_leaves_other_granted_lesson_as_draft(self):
        self.fr.grants[0]['lessons'].append('lesson-unassigned')
        result = self.apply(limit=1)
        self.assertEqual(result['changed_lessons'], 1)
        self.assertEqual(sum(row['is_draft'] for row in self.fr.tables['Course Lesson'].values()), 1)

    def test_real_join_queries_select_only_valid_active_owned_source_assignments(self):
        db = sqlite3.connect(':memory:'); self.addCleanup(db.close)
        db.create_function('CONCAT', -1, lambda *parts: ''.join(str(p) for p in parts))
        db.executescript('''
          CREATE TABLE `tabAVO Course Access`(account TEXT,sync_status TEXT,grant TEXT,enrollment TEXT,
            mapped_user TEXT,mapped_course TEXT,source_access_id TEXT,source_contact_id TEXT,source_course_id TEXT);
          CREATE TABLE `tabLMS Access Grant`(name TEXT,status TEXT,member TEXT,course TEXT);
          CREATE TABLE `tabLMS Enrollment`(name TEXT,member TEXT,course TEXT);
          CREATE TABLE `tabUser`(name TEXT,custom_avo_account TEXT,custom_avo_contact_id TEXT);
          CREATE TABLE `tabLMS Course`(name TEXT,custom_avo_account TEXT,custom_avo_id TEXT);
          CREATE TABLE `tabLMS Access Grant Lesson`(parent TEXT,parenttype TEXT,parentfield TEXT,lesson TEXT);
          CREATE TABLE `tabCourse Lesson`(name TEXT,course TEXT,custom_avo_id TEXT,custom_avo_account TEXT,
            is_draft INT,publication_audience TEXT,lesson_published_at TEXT,include_in_preview INT);
          INSERT INTO `tabAVO Course Access` VALUES('mv-centr','Applied','avo-mv-centr-grant-10',
            'avo-mv-centr-enrollment-20-30','user','course','10','20','30');
          INSERT INTO `tabLMS Access Grant` VALUES('avo-mv-centr-grant-10','Active','user','course');
          INSERT INTO `tabLMS Enrollment` VALUES('avo-mv-centr-enrollment-20-30','user','course');
          INSERT INTO `tabUser` VALUES('user','mv-centr','20');
          INSERT INTO `tabLMS Course` VALUES('course','mv-centr','30');
          INSERT INTO `tabLMS Access Grant Lesson` VALUES('avo-mv-centr-grant-10','LMS Access Grant','lessons','allowed');
          INSERT INTO `tabCourse Lesson` VALUES('allowed','course','40','mv-centr',1,NULL,NULL,0);
          INSERT INTO `tabCourse Lesson` VALUES('unassigned','course','41','mv-centr',1,NULL,NULL,0);
        ''')
        query = lambda sql: db.execute(sql.replace('%s', '?'), ('mv-centr',)).fetchall()
        self.assertEqual(query(operator.BAD_PARENT_SQL), [(0,)])
        self.assertEqual(query(operator.BAD_CHILD_SQL), [(0,)])
        self.assertEqual([row[0] for row in query(operator.CANDIDATE_SQL)], ['allowed'])
        db.execute("UPDATE `tabLMS Access Grant` SET status='Frozen'")
        self.assertEqual(query(operator.CANDIDATE_SQL), [])
        db.execute("UPDATE `tabLMS Access Grant` SET status='Active'")
        db.execute("UPDATE `tabAVO Course Access` SET sync_status='Superseded'")
        self.assertEqual(query(operator.CANDIDATE_SQL), [])
        db.execute("UPDATE `tabAVO Course Access` SET sync_status='Applied',mapped_user=NULL")
        self.assertEqual(query(operator.BAD_PARENT_SQL), [(1,)])
        db.execute("UPDATE `tabAVO Course Access` SET mapped_user='user'")
        db.execute("UPDATE `tabUser` SET custom_avo_account='iomp'")
        self.assertEqual(query(operator.BAD_PARENT_SQL), [(1,)])
        db.execute("UPDATE `tabUser` SET custom_avo_account='mv-centr'")
        db.execute("UPDATE `tabCourse Lesson` SET custom_avo_account='iomp' WHERE name='allowed'")
        self.assertEqual(query(operator.BAD_CHILD_SQL), [(1,)])
        db.execute("UPDATE `tabCourse Lesson` SET custom_avo_account='mv-centr' WHERE name='allowed'")
        db.execute('DELETE FROM `tabLMS Enrollment`')
        self.assertEqual(query(operator.BAD_PARENT_SQL), [(1,)])


if __name__ == '__main__': unittest.main()

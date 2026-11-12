"""Synthetic numbering regressions; no real site, credentials, or course content."""
import importlib.util
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import patch


class Doc(dict):
    def __init__(self, doctype='Course Lesson', previous=None, **values):
        super().__init__(doctype=doctype, custom_lms_id=None, custom_avo_account=None, custom_avo_id=None)
        self.update(values)
        self.previous = previous
    def __getattr__(self, name):
        return self[name]
    def set(self, key, value):
        self[key] = value
    def is_new(self):
        return self.previous is None and not self.get('name')
    def get_doc_before_save(self):
        return self.previous


class NumberingTest(unittest.TestCase):
    def setUp(self):
        self.rows = {'LMS Course': [], 'Course Lesson': []}
        self.fields = {dt: {key: types.SimpleNamespace(unique=0) for key in
            ('custom_lms_id', 'custom_avo_account', 'custom_avo_id')} for dt in self.rows}
        self.series = {}
        self.sql = []
        self.schema_writes = []
        self.allow_import = True
        self.mapping_installs = 0
        f = types.ModuleType('frappe')
        f.local = types.SimpleNamespace(site='my-lk.mv-centr.ru')
        f.PermissionError, f.ValidationError = PermissionError, ValueError
        f.throw = lambda message, kind: (_ for _ in ()).throw(kind(message))
        def only_for(role):
            self.assertEqual(role, 'System Manager')
            if not self.allow_import:
                raise PermissionError('import denied')
        f.only_for = only_for
        def meta(doctype):
            return types.SimpleNamespace(has_field=lambda key: key in self.fields[doctype],
                get_field=lambda key: self.fields[doctype].get(key))
        f.get_meta = meta
        def get_all(doctype, fields, **kwargs):
            return [{key: row.get(key) for key in fields} for row in self.rows[doctype]]
        f.get_all = get_all
        def sql(query, args):
            self.sql.append((query, args))
            if query.startswith('INSERT INTO'):
                key, floor = args
                self.series[key] = max(self.series.get(key, 0), floor)
            elif query.startswith('SELECT'):
                return [(self.series[args[0]],)] if args[0] in self.series else []
            elif query.startswith('UPDATE'):
                self.series[args[1]] = args[0]
            else:
                raise AssertionError('unexpected SQL')
        def exists(doctype, filters):
            return any(all(row.get(key) == value for key, value in filters.items()) for row in self.rows[doctype])
        def set_value(doctype, name, key, value, **kwargs):
            self.assertFalse(kwargs['update_modified'])
            row = next(row for row in self.rows[doctype] if row['name'] == name)
            row[key] = value
        def get_value(doctype, name, fields, **kwargs):
            row = next((row for row in self.rows[doctype] if row['name'] == name), None)
            return {key: row.get(key) for key in fields} if row else None
        f.db = types.SimpleNamespace(sql=sql, exists=exists, set_value=set_value, get_value=get_value)
        def create_fields(fields, update):
            self.assertTrue(update)
            self.schema_writes.append(fields)
            for doctype, values in fields.items():
                for field in values:
                    self.assertNotIn('default', field)
                    self.assertEqual(field['read_only'], 1)
                    self.assertEqual(field['no_copy'], 1)
                    self.fields[doctype][field['fieldname']] = types.SimpleNamespace(unique=field['unique'])
        def install_mapping():
            self.mapping_installs += 1
            for fields in self.fields.values():
                fields['custom_avo_account'] = types.SimpleNamespace(unique=0)
                fields['custom_avo_id'] = types.SimpleNamespace(unique=0)
        source = types.ModuleType('lms.lms.avo_import')
        source.SITE_ACCOUNTS = {'my-lk.mv-centr.ru': ('mv-centr', ''),
            'my-lk.iomp.ru': ('iomp', ''), 'my-lk.mastervision.su': ('mastervision', '')}
        custom = types.ModuleType('frappe.custom.doctype.custom_field.custom_field')
        custom.create_custom_fields = create_fields
        mapping = types.ModuleType('lms.lms.avo_mapping_fields')
        mapping.execute = install_mapping
        self.patches = patch.dict(sys.modules, {'frappe': f, 'lms.lms.avo_import': source,
            'frappe.custom.doctype.custom_field.custom_field': custom, 'lms.lms.avo_mapping_fields': mapping})
        self.patches.start()
        self.addCleanup(self.patches.stop)
        self.frappe = f
        spec = importlib.util.spec_from_file_location('numbering_under_test', Path(__file__).with_name('course_numbering.py'))
        self.module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.module)
        for floors in self.module.SOURCE_FLOORS.values():
            floors.update({'LMS Course': 100, 'Course Lesson': 1000})

    def test_native_numbers_are_global_per_doctype_and_keep_provenance_empty(self):
        one, two, course = Doc(), Doc(), Doc('LMS Course')
        for doc in (one, two, course): self.module.assign(doc)
        self.assertEqual((one['custom_lms_id'], two['custom_lms_id'], course['custom_lms_id']), ('1001', '1002', '101'))
        self.assertIsNone(one['custom_avo_account'])
        self.assertIsNone(one['custom_avo_id'])
        self.assertTrue(any('FOR UPDATE' in query for query, _ in self.sql))

    def test_counter_does_not_reuse_deleted_numbers_or_fill_old_gaps(self):
        doc = Doc(); self.module.assign(doc)
        # Successful earlier allocations persist in the series even with no documents remaining.
        next_doc = Doc(); self.module.assign(next_doc)
        self.assertEqual(next_doc['custom_lms_id'], '1002')
        self.module._reserve('Course Lesson', 'mv-centr', 9)
        last = Doc(); self.module.assign(last)
        self.assertEqual(last['custom_lms_id'], '1003')

    def test_import_preserves_source_id_and_advances_next_native_number(self):
        imported = Doc(custom_avo_account='mv-centr', custom_avo_id='1400')
        self.module.assign(imported)
        self.assertEqual(imported['custom_lms_id'], '1400')
        native = Doc(); self.module.assign(native)
        self.assertEqual(native['custom_lms_id'], '1401')
        self.assertIsNone(native['custom_avo_id'])

    def test_import_below_floor_does_not_reset_sequence(self):
        imported = Doc(custom_avo_account='mv-centr', custom_avo_id='26')
        self.module.assign(imported)
        native = Doc(); self.module.assign(native)
        self.assertEqual(imported['custom_lms_id'], '26')
        self.assertEqual(native['custom_lms_id'], '1001')

    def test_import_context_gives_skeleton_identity_once_and_is_restored(self):
        with self.module.importing_source('Course Lesson', 'mv-centr', '26'):
            imported = Doc(); self.module.assign(imported)
            native = Doc(); self.module.assign(native)
        after = Doc(); self.module.assign(after)
        self.assertEqual((imported['custom_lms_id'], imported['custom_avo_id'], imported['custom_avo_account']), ('26', '26', 'mv-centr'))
        self.assertEqual((native['custom_lms_id'], after['custom_lms_id']), ('1001', '1002'))
        self.assertIsNone(native['custom_avo_id'])
        with self.assertRaises(RuntimeError):
            with self.module.importing_source('Course Lesson', 'mv-centr', '27'):
                raise RuntimeError('abort import')
        after_abort = Doc(); self.module.assign(after_abort)
        self.assertIsNone(after_abort['custom_avo_id'])

    def test_context_cannot_cross_account_or_change_an_explicit_source(self):
        with self.assertRaises(PermissionError):
            with self.module.importing_source('Course Lesson', 'iomp', '26'): pass
        with self.module.importing_source('Course Lesson', 'mv-centr', '26'):
            with self.assertRaises(PermissionError):
                self.module.assign(Doc(custom_avo_account='mv-centr', custom_avo_id='27'))

    def test_native_client_cannot_pick_id_or_forge_source_identity(self):
        with self.assertRaises(ValueError): self.module.assign(Doc(custom_lms_id='42'))
        self.allow_import = False
        with self.assertRaises(PermissionError): self.module.assign(Doc(custom_avo_account='mv-centr', custom_avo_id='42'))
        with self.assertRaises(PermissionError):
            with self.module.importing_source('Course Lesson', 'mv-centr', '42'): pass

    def test_bad_ids_partial_sources_and_future_import_collisions_fail_before_write(self):
        for value in ('0', '01', '１', '-1', '1.5', str(1 << 63), True, None):
            with self.subTest(value=value), self.assertRaises(ValueError): self.module._number(value)
        for values in ({'custom_avo_account':'iomp', 'custom_avo_id':'26'},
                       {'custom_avo_account':'mv-centr'}, {'custom_avo_id':'26'},
                       {'custom_avo_account':'mv-centr','custom_avo_id':'26','custom_lms_id':'27'}):
            with self.subTest(values=values), self.assertRaises(ValueError): self.module.assign(Doc(**values))
        self.rows['Course Lesson'].append({'name':'native', 'custom_lms_id':'1400'})
        with self.assertRaises(ValueError): self.module.assign(Doc(custom_avo_account='mv-centr', custom_avo_id='1400'))
        self.assertEqual(self.series, {})

    def test_site_counters_are_separate_and_unknown_sites_do_not_get_numbered(self):
        mv = Doc(); self.module.assign(mv)
        self.frappe.local.site = 'my-lk.iomp.ru'
        iomp = Doc(); self.module.assign(iomp)
        self.assertEqual(mv['custom_lms_id'], iomp['custom_lms_id'])
        self.assertEqual(len(self.series), 2)
        self.frappe.local.site = 'unconfigured.local'
        untouched = Doc(); self.module.assign(untouched)
        self.assertIsNone(untouched['custom_lms_id'])
        with self.assertRaises(RuntimeError): self.module.execute()

    def test_saved_identity_cannot_change_but_content_can(self):
        previous = {'custom_lms_id':'26','custom_avo_account':'mv-centr','custom_avo_id':'26'}
        doc = Doc(previous=previous, name='saved', **previous)
        doc['content'] = 'Updated lesson text'
        self.module.validate_identity(doc)
        for key in previous:
            modified = Doc(previous=previous, name='saved', **previous)
            modified[key] = '27'
            with self.subTest(key=key), self.assertRaises(PermissionError): self.module.validate_identity(modified)

    def test_validation_falls_back_to_stored_identity_if_prior_doc_missing(self):
        self.rows['Course Lesson'].append({'name':'saved','custom_lms_id':'26','custom_avo_account':None,'custom_avo_id':None})
        doc = Doc(name='saved', custom_lms_id='26')
        self.module.validate_identity(doc)
        doc['custom_lms_id'] = '27'
        with self.assertRaises(PermissionError): self.module.validate_identity(doc)

    def test_migration_dry_run_and_rerun_preserve_imports_native_ids_and_counter(self):
        self.rows['LMS Course'] = [
            {'name':'imported', 'custom_avo_account':'mv-centr','custom_avo_id':'11'},
            {'name':'native'}, {'name':'numbered','custom_lms_id':'150'},
        ]
        key = self.module._series_name('LMS Course', 'mv-centr')
        self.series[key] = 160
        preview = self.module.execute(dry_run=True)
        self.assertEqual(preview['doctypes']['LMS Course']['next_new_id'], '162')
        self.assertEqual(self.schema_writes, [])
        self.assertNotIn('custom_lms_id', self.rows['LMS Course'][0])
        result = self.module.execute()
        self.assertEqual(result['doctypes']['LMS Course']['backfilled'], 2)
        self.assertEqual([row['custom_lms_id'] for row in self.rows['LMS Course']], ['11', '161', '150'])
        self.assertNotIn('custom_avo_id', self.rows['LMS Course'][1])
        rerun = self.module.execute()
        self.assertEqual(rerun['doctypes']['LMS Course']['backfilled'], 0)
        self.assertEqual(self.series[key], 161)
        self.assertEqual(self.schema_writes[-2]['LMS Course'][0]['unique'], 1)

    def test_migration_preflight_rejects_conflicting_rows_without_schema_writes(self):
        scenarios = [
            [{'name':'a','custom_avo_account':'mv-centr','custom_avo_id':'11'},
             {'name':'b','custom_avo_account':'mv-centr','custom_avo_id':'11'}],
            [{'name':'a','custom_lms_id':'11'}, {'name':'b','custom_avo_account':'mv-centr','custom_avo_id':'11'}],
            [{'name':'a','custom_avo_account':'iomp','custom_avo_id':'11'}],
            [{'name':'a','custom_lms_id':'12','custom_avo_account':'mv-centr','custom_avo_id':'11'}],
        ]
        for rows in scenarios:
            self.rows['LMS Course'] = rows
            with self.subTest(rows=rows), self.assertRaises(ValueError): self.module.execute()
        self.assertEqual(self.schema_writes, [])
        self.assertEqual(self.series, {})

    def test_missing_mapping_schema_is_installed_only_by_non_dry_migration(self):
        for doctype in self.fields:
            self.fields[doctype] = {}
        self.rows['LMS Course'] = [{'name':'native'}]
        self.module.execute(dry_run=True)
        self.assertEqual(self.mapping_installs, 0)
        self.module.execute()
        self.assertEqual(self.mapping_installs, 1)
        self.assertEqual(self.rows['LMS Course'][0]['custom_lms_id'], '101')

    def test_exhausted_or_unconfigured_sequence_fails_without_wrapping(self):
        self.module.SOURCE_FLOORS['mv-centr']['Course Lesson'] = 0
        inactive = Doc(); self.module.assign(inactive)
        self.assertIsNone(inactive['custom_lms_id'])
        with self.assertRaises(ValueError): self.module._next('Course Lesson', 'mv-centr')
        self.assertEqual(self.series, {})
        self.module.SOURCE_FLOORS['mv-centr']['Course Lesson'] = self.module.MAX_ID
        with self.assertRaises(ValueError): self.module.assign(Doc())
        key = self.module._series_name('Course Lesson', 'mv-centr')
        self.assertEqual(self.series[key], self.module.MAX_ID)

    def test_inactive_account_imports_source_ids_without_numbering_native_rows(self):
        self.frappe.local.site = 'my-lk.iomp.ru'
        self.module.SOURCE_FLOORS['iomp'] = {'LMS Course': None, 'Course Lesson': 0}
        self.rows['Course Lesson'] = [
            {'name':'source','custom_avo_account':'iomp','custom_avo_id':'6311'},
            {'name':'native','custom_lms_id':''}, {'name':'native-two'},
        ]
        preview = self.module.execute(dry_run=True)
        self.assertFalse(preview['numbering_enabled'])
        self.assertIsNone(preview['doctypes']['Course Lesson']['next_new_id'])
        self.assertEqual(preview['doctypes']['Course Lesson']['native_pending'], 2)
        self.assertEqual(preview['doctypes']['Course Lesson']['native_to_number'], 0)
        result = self.module.execute()
        self.assertFalse(result['numbering_enabled'])
        self.assertEqual(self.rows['Course Lesson'][0]['custom_lms_id'], '6311')
        self.assertIsNone(self.rows['Course Lesson'][1]['custom_lms_id'])
        self.assertNotIn('custom_lms_id', self.rows['Course Lesson'][2])
        native = Doc(custom_lms_id=''); self.module.assign(native)
        self.assertIsNone(native['custom_lms_id'])
        imported = Doc(custom_avo_account='iomp', custom_avo_id='6312')
        self.module.assign(imported)
        self.assertEqual(imported['custom_lms_id'], '6312')
        key = self.module._series_name('Course Lesson', 'iomp')
        self.assertEqual(self.series[key], 6312)


if __name__ == '__main__':
    unittest.main()

"""Offline cover-pass orchestration; all target calls and downloads are mocked."""
import json
from contextlib import closing
from pathlib import Path
import shutil
import sqlite3
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
import uuid

import assets
import covers
import importer
import run as mod
import status as status_module


def target(cid):
    return {'name': f'course-{cid}', 'custom_avo_account': 'mastervision',
            'custom_avo_id': str(cid), 'custom_lms_id': str(cid), 'published': 0}


class Cursor:
    def __init__(self, rows): self.rows = rows
    def fetchall(self): return self.rows
    def __iter__(self): return iter(self.rows)


class ArchiveDB:
    def __init__(self, store): self.store = store
    def execute(self, sql, parameters=()):
        if sql == "SELECT id FROM courses WHERE state='excluded'":
            return Cursor([(cid,) for cid in sorted(self.store.excluded)])
        if sql == 'SELECT id,title FROM courses ORDER BY id':
            return Cursor(self.store.catalog_rows)
        if sql == 'SELECT stage FROM errors WHERE consecutive>=?':
            return Cursor([])
        raise AssertionError('unexpected cover archive query')


class Store:
    def __init__(self):
        self.count = 0
        self.events = []
        self.excluded, self.catalog_rows = set(), []
        self.db = ArchiveDB(self)
        self.completed_metadata = Mock(side_effect=lambda cid: {'cover_url': f'https://f1.autoweboffice.com/private/{cid}.png'})
        self.report = Mock()
    def error(self, stage, failed):
        assert stage == 'cover'
        self.count = self.count + 1 if failed else 0
        return self.count
    def event(self, *args): self.events.append(args)


class CoverRunnerTests(unittest.TestCase):
    def fixture(self, count=12, target_ids=None):
        store = Store()
        client = Mock(site='my-lk.mastervision.su', account='mastervision')
        client.call.return_value = {'documents': [target(cid) for cid in (target_ids or range(1, count + 1))], 'has_next_page': False}
        cache = SimpleNamespace(fetch=Mock(return_value=(b'PRIVATE SYNTHETIC IMAGE', 'png')), close=Mock())
        rows = [{'id': cid, 'title': 'PRIVATE COURSE TITLE'} for cid in range(1, count + 1)]
        store.catalog_rows = rows
        return store, rows, client, cache

    def test_all_excluded_courses_never_read_target_metadata_or_download(self):
        store, rows, client, cache = self.fixture(2)
        store.excluded = {1, 2}
        with patch.object(covers, 'sync_cover') as sync, patch.object(mod, 'emit') as emit:
            mod.transfer_covers(store, rows, client, cache, True)
        client.call.assert_not_called(); store.completed_metadata.assert_not_called()
        cache.fetch.assert_not_called(); sync.assert_not_called(); emit.assert_not_called()
        self.assertEqual(store.events, [])

    def test_excluded_course_is_skipped_even_when_its_target_document_exists(self):
        store, rows, client, cache = self.fixture(4, target_ids=[1, 2, 4])
        store.excluded = {2}
        with patch.object(covers, 'sync_cover', return_value={'status':'created'}) as sync, patch.object(mod, 'emit'):
            mod.transfer_covers(store, rows, client, cache, True)
        self.assertEqual([call.args[0] for call in store.completed_metadata.call_args_list], [1, 4])
        self.assertEqual([call.args[1] for call in sync.call_args_list], [1, 4])
        self.assertEqual(cache.fetch.call_count, 2)

    def test_only_created_target_courses_use_completed_metadata_and_anonymous_assets(self):
        store, rows, client, cache = self.fixture(4, target_ids=[2, 4])
        output = []
        with patch.object(covers, 'sync_cover', return_value={'status': 'created'}) as sync, patch.object(mod, 'emit', side_effect=output.append):
            mod.transfer_covers(store, rows, client, cache, True)
        self.assertEqual([call.args[0] for call in store.completed_metadata.call_args_list], [2, 4])
        self.assertEqual([call.args[1] for call in sync.call_args_list], [2, 4])
        self.assertTrue(all(call.kwargs == {'apply': True} for call in sync.call_args_list))
        self.assertEqual(cache.fetch.call_count, 2)
        self.assertEqual(client.call.call_args.args[1]['filters'], [['custom_avo_account', '=', 'mastervision']])
        self.assertEqual(output, [{'course': 2, 'status': 'cover_created'}, {'course': 4, 'status': 'cover_created'}])
        self.assertNotIn('PRIVATE', repr(output) + repr(store.events))
        self.assertNotIn('https://', repr(output) + repr(store.events))

    def test_absent_source_cover_never_downloads_or_calls_sync(self):
        store, rows, client, cache = self.fixture(1)
        store.completed_metadata.return_value = {'cover_url': None}; store.completed_metadata.side_effect = None
        output = []
        with patch.object(covers, 'sync_cover') as sync, patch.object(mod, 'emit', side_effect=output.append):
            mod.transfer_covers(store, rows, client, cache, True)
        cache.fetch.assert_not_called(); sync.assert_not_called()
        self.assertEqual(output, [{'course': 1, 'status': 'no_source_cover'}])

    def test_tenth_predictable_cover_problem_stops_before_course_eleven(self):
        store, rows, client, cache = self.fixture()
        cache.fetch.side_effect = importer.Review('asset_download_failed')
        output = []
        with patch.object(covers, 'sync_cover') as sync, patch.object(mod, 'emit', side_effect=output.append):
            with self.assertRaisesRegex(mod.Stop, '^paused_after_ten_cover_problems$'):
                mod.transfer_covers(store, rows, client, cache, True)
        self.assertEqual(cache.fetch.call_count, 10)
        self.assertEqual(store.count, 10)
        self.assertEqual(len(store.events), 10)
        self.assertEqual(output[-1], {'course': 10, 'status': 'cover_review', 'code': 'asset_download_failed'})
        sync.assert_not_called()

    def test_success_resets_cover_review_streak(self):
        store, rows, client, cache = self.fixture(19)
        outcomes = [importer.Review('cover_course_missing')] * 9 + [{'status': 'created'}] + [importer.Review('cover_course_missing')] * 9
        with patch.object(covers, 'sync_cover', side_effect=outcomes) as sync, patch.object(mod, 'emit'):
            mod.transfer_covers(store, rows, client, cache, False)
        self.assertEqual(sync.call_count, 19)
        self.assertEqual(store.count, 9)
        self.assertIn(('cover', 10, None, 'cover_created'), store.events)

    def test_uncertain_write_propagates_without_retry_or_next_course(self):
        store, rows, client, cache = self.fixture(6)
        outcomes = [{'status': 'already_imported'}, {'status': 'created'}, importer.Stop('cover_write_uncertain')]
        with patch.object(covers, 'sync_cover', side_effect=outcomes) as sync, patch.object(mod, 'emit'):
            with self.assertRaisesRegex(importer.Stop, '^cover_write_uncertain$'):
                mod.transfer_covers(store, rows, client, cache, True)
        self.assertEqual(sync.call_count, 3)
        self.assertEqual(cache.fetch.call_count, 3)
        self.assertEqual([event[1] for event in store.events], [1, 2])

    def test_target_account_identity_ambiguity_stops_before_source_fetch(self):
        for documents, has_next in [([target(1)], True),
                ([{**target(1), 'custom_avo_account': 'mv-centr'}], False),
                ([{**target(1), 'custom_lms_id': '2'}], False), ([target(1), target(1)], False)]:
            store, rows, client, cache = self.fixture(2)
            client.call.return_value = {'documents': documents, 'has_next_page': has_next}
            with self.subTest(documents=len(documents), has_next=has_next), self.assertRaises(mod.Stop):
                mod.transfer_covers(store, rows, client, cache, True)
            store.completed_metadata.assert_not_called(); cache.fetch.assert_not_called()

    def test_unverified_or_corrupt_completed_source_stops_before_downloading(self):
        store, rows, client, cache = self.fixture(2)
        store.completed_metadata.side_effect = mod.StorageError('source_digest_mismatch')
        with patch.object(covers, 'sync_cover') as sync:
            with self.assertRaisesRegex(mod.StorageError, '^source_digest_mismatch$'):
                mod.transfer_covers(store, rows, client, cache, True)
        cache.fetch.assert_not_called(); sync.assert_not_called()

    def test_covers_only_main_uses_stored_metadata_and_never_starts_source_browser_or_lesson_import(self):
        store, rows, client, cache = self.fixture(1)
        output = []
        with patch.object(mod, 'Store') as constructor, patch.object(mod, 'Transport') as transport, \
             patch.object(mod, 'catalog') as catalog, patch.object(importer, 'MCPClient', return_value=client), \
             patch.object(importer, 'Importer') as lesson_importer, patch.object(assets, 'AssetCache', return_value=cache), \
             patch.object(covers, 'sync_cover', return_value={'status': 'created'}), \
             patch.object(mod, 'emit', side_effect=output.append), \
             patch('sys.argv', ['run.py', '--stored', '--covers-only', '--apply']):
            constructor.return_value.__enter__.return_value = store
            self.assertEqual(mod.main(), 0)
        transport.assert_not_called(); catalog.assert_not_called()
        lesson_importer.return_value.import_course.assert_not_called()
        cache.close.assert_called_once(); client.close.assert_called_once()
        self.assertEqual(output[-1], {'status': 'covers_finished'})


class ReadonlyStatusTests(unittest.TestCase):
    def database(self, account='mastervision'):
        workspace = Path(__file__).resolve().parents[3]
        parent = workspace / '.tmp-mastervision-status-tests'; parent.mkdir(exist_ok=True)
        directory = parent / ('fixture-' + uuid.uuid4().hex); directory.mkdir()
        def cleanup():
            if directory.resolve().parent != parent.resolve() or not directory.name.startswith('fixture-'):
                raise RuntimeError('unsafe_fixture_cleanup')
            shutil.rmtree(directory)
        self.addCleanup(cleanup)
        path = directory / 'synthetic.sqlite'
        with closing(sqlite3.connect(path)) as db:
            db.executescript('CREATE TABLE meta(account,origin,site); CREATE TABLE courses(state,title); '
                'CREATE TABLE course_checkpoints(lesson_digests); CREATE TABLE errors(stage,consecutive); '
                'CREATE TABLE events(id,at,stage,course,lesson,status,private_source);')
            db.execute('INSERT INTO meta VALUES(?,?,?)', (account, 'https://shop.mastervision.su', 'my-lk.mastervision.su'))
            db.execute('INSERT INTO courses VALUES(?,?)', ('imported', 'PRIVATE SOURCE TITLE AND URL'))
            db.execute('INSERT INTO course_checkpoints VALUES(?)', (json.dumps([[11, 'PRIVATE DIGEST']]),))
            db.execute('INSERT INTO errors VALUES(?,?)', ('import', 0))
            db.execute('INSERT INTO events VALUES(?,?,?,?,?,?,?)', (1, '2026-11-12T12:00:00Z', 'import', 7, 11, 'created', 'PRIVATE COOKIE'))
            db.commit()
        return path

    def test_status_does_not_emit_source_fields_or_modify_database(self):
        path = self.database(); before = path.read_bytes()
        result = status_module.status(path)
        self.assertEqual(result['catalog_courses'], 1)
        self.assertEqual(result['completed_source_lessons'], 1)
        self.assertNotIn('PRIVATE', json.dumps(result))
        self.assertEqual(path.read_bytes(), before)

    def test_status_rejects_foreign_account_without_modifying_it(self):
        path = self.database('mv-centr'); before = path.read_bytes()
        with self.assertRaisesRegex(ValueError, '^status_account_mismatch$'):
            status_module.status(path)
        self.assertEqual(path.read_bytes(), before)


if __name__ == '__main__': unittest.main()

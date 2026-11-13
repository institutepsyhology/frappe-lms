"""Synthetic local SQLite archives; never open the real migration directory."""
from contextlib import closing
import copy
import hashlib
import json
from pathlib import Path
import shutil
import sqlite3
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import uuid
import zlib

import storage
from importer import Stop as ImportStop


def value(text='synthetic private lesson text'):
    return {'account':storage.ACCOUNT,'origin':storage.ORIGIN,'html':text,'parsed':None}


def verified_course(ids=(11,12), title='Course'):
    return {**value('synthetic course html'), 'verified':True, 'error':None, 'parsed':{
        'course_id':7,'title':title,'lesson_ids':list(ids),
        'lessons':[{'id':ident,'title':'Lesson '+str(ident)} for ident in ids]}}


def verified_lesson(ident, version='original'):
    return {**value('synthetic lesson html '+version), 'verified':True, 'error':None, 'parsed':{'payload':{
        'account':storage.ACCOUNT,'source_origin':storage.ORIGIN,'course_id':7,'lesson_id':ident,
        'course_title':'Course','lesson_title':'Lesson '+str(ident),'format':'ape',
        'ape':{'name':'page','children':[{'name':'text','fields':{'html':version}}]}}}}


def uuid_lesson(root_id, block_id, body='original'):
    record=verified_lesson(11,body)
    record['html']='fresh raw HTML '+root_id+' '+block_id
    ape=record['parsed']['payload']['ape']
    ape['id']=root_id;ape['children'][0]['id']=block_id
    return record


class StorageTests(unittest.TestCase):
    def test_permanent_exclusions_are_reported_without_rewriting_source_ids(self):
        store=self.store();cid=207;ids=(11,1976,12)
        store.catalog([{'id':cid,'title':'Course'}])
        course=verified_course(ids);course['parsed']['course_id']=cid
        digest=store.capture('course',cid,0,course);pairs=[]
        for lid in ids:
            lesson=verified_lesson(lid);lesson['parsed']['payload']['course_id']=cid
            pairs.append((lid,store.capture('lesson',cid,lid,lesson)))
        store.bind_course(cid,digest,pairs);before=store.completed_course(cid)
        store.mark(cid,'imported');store.event('import',cid,1976,'warning',['owner_excluded_obsolete_lesson'])
        self.assertEqual(store.summary(),{'imported':1});self.assertEqual(store.completed_course(cid),before)
        report=store.report().read_text(encoding='utf-8')
        self.assertIn('207',report);self.assertIn('1976',report);self.assertIn('owner_excluded_obsolete_lesson',report)
        with self.assertRaisesRegex(storage.StorageError,'invalid_partial_course'):store.mark(cid,'partial')

    def test_partial_is_scoped_preserves_checkpoint_and_reports_pending(self):
        store=self.store();cid=598;ids=(11,7544,12)
        store.catalog([{'id':cid,'title':'Course'}])
        course=verified_course(ids);course['parsed']['course_id']=cid
        digest=store.capture('course',cid,0,course);pairs=[]
        for lid in ids:
            lesson=verified_lesson(lid);lesson['parsed']['payload']['course_id']=cid
            pairs.append((lid,store.capture('lesson',cid,lid,lesson)))
        store.bind_course(cid,digest,pairs);before=store.completed_course(cid)
        store.mark(cid,'partial');store.event('import',cid,7544,'review',['owner_deferred_lesson'])
        self.assertEqual(store.summary(),{'partial':1})
        self.assertEqual(store.completed_course(cid),before)
        store.bind_course(cid,digest,pairs)
        self.assertEqual(store.summary(),{'partial':1})
        store.course(cid,list(ids),digest);self.assertEqual(store.summary(),{'partial':1})
        report=store.report().read_text(encoding='utf-8')
        self.assertIn('partial: 1',report);self.assertIn('7544',report);self.assertIn('owner_deferred_lesson',report)
        store.catalog([{'id':599,'title':'Other'}])
        with self.assertRaisesRegex(storage.StorageError,'invalid_partial_course'):store.mark(599,'partial')

    def setUp(self):
        self.parent=Path(__file__).resolve().parents[3]/'.tmp-mastervision-storage-tests'
        self.parent.mkdir(exist_ok=True)
        self.folder=self.parent/('fixture-'+uuid.uuid4().hex)
        self.folder.mkdir()
        self.addCleanup(self.cleanup)
        self.archive=self.folder/'archive'

    def cleanup(self):
        if self.folder.parent.resolve()!=self.parent.resolve() or not self.folder.name.startswith('fixture-'):
            raise RuntimeError('unsafe_fixture_cleanup')
        shutil.rmtree(self.folder)

    def store(self):
        store=storage.Store(self.archive);self.addCleanup(store.close);return store

    def test_compressed_exact_hashed_idempotent_capture(self):
        store=self.store();payload=value('Hello {name} <b>private marker</b>')
        first=store.capture('lesson',7,11,payload)
        self.assertEqual(first,hashlib.sha256(storage.canonical(payload)).hexdigest())
        self.assertEqual(store.capture('lesson',7,11,payload),first)
        self.assertEqual(store.latest('lesson',7,11),payload)
        row=store.db.execute('SELECT payload FROM captures').fetchone()
        self.assertNotIn(b'private marker',row['payload'])
        self.assertEqual(json.loads(zlib.decompress(row['payload'])),payload)
        self.assertEqual(store.db.execute('SELECT COUNT(*) FROM captures').fetchone()[0],1)

    def test_read_only_audit_snapshot_does_not_block_progress_commits(self):
        store = self.store()
        path = self.archive/'mastervision-migration.sqlite'
        with closing(sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True)) as reader:
            reader.execute('BEGIN')
            self.assertEqual(reader.execute('SELECT COUNT(*) FROM events').fetchone()[0],0)
            store.event('audio',None,None,'audio_staged')
            self.assertEqual(reader.execute('SELECT COUNT(*) FROM events').fetchone()[0],0)
            reader.rollback()
            self.assertEqual(reader.execute('SELECT COUNT(*) FROM events').fetchone()[0],1)

    def test_foreign_db_never_mutated_or_given_new_lock(self):
        self.archive.mkdir();path=self.archive/'mastervision-migration.sqlite'
        with closing(sqlite3.connect(path)) as db:
            db.execute('CREATE TABLE meta(account TEXT,origin TEXT,site TEXT)')
            db.execute('INSERT INTO meta VALUES(?,?,?)',('mv-centr','https://shop.mv-centr.ru','my-lk.mv-centr.ru'))
            db.commit()
        before=path.read_bytes();names={x.name for x in self.archive.iterdir()}
        with self.assertRaisesRegex(storage.StorageError,'account_mismatch'):storage.Store(self.archive)
        self.assertEqual(path.read_bytes(),before)
        self.assertEqual({x.name for x in self.archive.iterdir()},names)

    def test_unknown_schema_and_empty_meta_never_modified(self):
        for index,sql in enumerate(('CREATE TABLE foreign_records(secret TEXT)','CREATE TABLE meta(account TEXT,origin TEXT,site TEXT)')):
            folder=self.folder/str(index);folder.mkdir();path=folder/'mastervision-migration.sqlite'
            with closing(sqlite3.connect(path)) as db:db.execute(sql);db.commit()
            before=path.read_bytes()
            with self.assertRaises(storage.StorageError):storage.Store(folder)
            self.assertEqual(path.read_bytes(),before)
            self.assertFalse((folder/'worker.lock.sqlite').exists())

    def test_fixed_binding_rejected_before_directory_created(self):
        with patch.object(storage,'ORIGIN','https://shop.mv-centr.ru'):
            with self.assertRaisesRegex(storage.StorageError,'account_mismatch'):storage.Store(self.archive)
        self.assertFalse(self.archive.exists())

    def test_single_worker_and_idempotent_close(self):
        store=self.store()
        with self.assertRaisesRegex(storage.StorageError,'worker_already_running'):storage.Store(self.archive)
        store.close();store.close()
        with storage.Store(self.archive) as reopened:self.assertEqual(reopened.summary(),{})

    def test_initialization_exception_releases_lock(self):
        original=sqlite3.connect
        def connect(path,*args,**kwargs):
            if str(path).endswith('mastervision-migration.sqlite'):
                raise sqlite3.OperationalError('synthetic connection failure')
            return original(path,*args,**kwargs)
        with patch.object(storage.sqlite3,'connect',side_effect=connect):
            with self.assertRaises(sqlite3.OperationalError):storage.Store(self.archive)
        with storage.Store(self.archive) as reopened:self.assertEqual(reopened.summary(),{})

    def test_db_close_exception_still_releases_worker_lock(self):
        store=self.store();actual=store.db;actual.close()
        class Broken:
            def close(self):raise RuntimeError('synthetic close failure')
        store.db=Broken()
        with self.assertRaisesRegex(RuntimeError,'synthetic close failure'):store.close()
        with storage.Store(self.archive) as reopened:self.assertEqual(reopened.summary(),{})

    def test_wrong_origin_types_ids_and_nan_rejected_without_captures(self):
        store=self.store()
        for kind,cid,lid,payload in [('lesson',7,11,{**value(),'origin':'https://shop.mv-centr.ru'}),
                ('course',True,0,value()),('catalog',7,1,value()),('lesson',7,0,value()),
                ('lesson',7,11,[]),('lesson',7,11,{**value(),'unknown':float('nan')})]:
            with self.assertRaises(storage.StorageError):store.capture(kind,cid,lid,payload)
        self.assertEqual(store.db.execute('SELECT COUNT(*) FROM captures').fetchone()[0],0)

    def test_low_disk_does_not_write(self):
        store=self.store()
        with patch.object(storage.shutil,'disk_usage',return_value=SimpleNamespace(free=1)):
            with self.assertRaisesRegex(storage.StorageError,'insufficient_private_archive_space'):
                store.capture('course',7,0,value())
        self.assertIsNone(store.latest('course',7))

    def test_corrupt_compression_digest_and_expansion_limit_are_fixed_errors(self):
        store=self.store();digest=store.capture('lesson',7,11,value('x'*300))
        original=store.db.execute('SELECT payload FROM captures').fetchone()[0]
        for blob,sha,code in [(b'not-zlib',digest,'compression_invalid'),(original,'0'*64,'digest_mismatch'),
                              (original+b'trailing',digest,'compression_invalid')]:
            store.db.execute('UPDATE captures SET payload=?,digest=?',(blob,sha));store.db.commit()
            with self.assertRaisesRegex(storage.StorageError,code):store.latest('lesson',7,11)
        store.db.execute('UPDATE captures SET payload=?,digest=?',(original,digest));store.db.commit()
        with patch.object(storage,'MAX_CAPTURE_BYTES',40):
            with self.assertRaisesRegex(storage.StorageError,'compression_invalid'):store.latest('lesson',7,11)

    def test_catalog_validates_whole_batch_and_preserves_imported_state(self):
        store=self.store();store.catalog([{'id':7,'title':'Original'}])
        for bad in ([{'id':7,'title':'Changed'},{'id':8,'title':None}],
                    [{'id':7,'title':'Changed'},{'id':7,'title':'Duplicate'}]):
            with self.assertRaises(storage.StorageError):store.catalog(bad)
        self.assertEqual(store.db.execute('SELECT title FROM courses').fetchone()[0],'Original')
        digest=store.capture('course',7,0,value());store.course(7,[11,12],digest);store.mark(7,'imported')
        store.course(7,[11,12],digest);self.assertEqual(store.summary(),{'imported':1})
        changed=store.capture('course',7,0,value('changed source'));store.course(7,[11,12,13],changed)
        self.assertEqual(store.summary(),{'collected':1})
        with self.assertRaisesRegex(storage.StorageError,'unknown_course_capture'):store.course(7,[11],'0'*64)
        with self.assertRaises(storage.StorageError):store.course(7,[11,11],changed)

    def test_error_limit_reset_and_safe_diagnostics(self):
        store=self.store()
        self.assertEqual([store.error('collect',True) for _ in range(10)],list(range(1,11)))
        self.assertEqual(store.error('collect',False),0)
        for args in [('collect','private text',None,'review',()),('collect',7,None,'student@example.test',()),
                     ('collect',7,None,'review',['https://example.test/private']),('unknown',7,None,'review',()),
                     ([],7,None,'review',())]:
            with self.assertRaisesRegex(storage.StorageError,'unsafe_diagnostic'):store.event(*args)
        with self.assertRaisesRegex(storage.StorageError,'unsafe_diagnostic'):store.error('private text',True)
        with self.assertRaisesRegex(storage.StorageError,'unsafe_diagnostic'):store.error([],True)
        with self.assertRaisesRegex(storage.StorageError,'invalid_course_state'):store.mark(7,[])

    def test_report_contains_only_counts_ids_fixed_urls_and_codes(self):
        store=self.store();store.catalog([{'id':7,'title':'PRIVATE TITLE student@example.test'}])
        store.capture('lesson',7,11,value('PRIVATE CONTENT secret_token'))
        store.mark(7,'review');store.event('collect',7,11,'review',['unsupported_block'])
        report=store.report().read_text(encoding='utf-8')
        for secret in ('PRIVATE TITLE','student@example.test','PRIVATE CONTENT','secret_token'):
            self.assertNotIn(secret,report)
        self.assertIn('id=11&lg=ru',report);self.assertIn('unsupported_block',report)
        store.event('collect',7,11,'captured');self.assertNotIn('unsupported_block',store.report().read_text(encoding='utf-8'))
        store.db.execute("UPDATE courses SET state='student@example.test'");store.db.commit()
        with self.assertRaisesRegex(storage.StorageError,'archive_state_invalid'):store.summary()

    def checkpoint_fixture(self, store):
        store.catalog([{'id':7,'title':'Course'}])
        course=store.capture('course',7,0,verified_course())
        pairs=[(ident,store.capture('lesson',7,ident,verified_lesson(ident))) for ident in (11,12)]
        return course,pairs

    def test_legacy_collected_state_without_checkpoint_cannot_be_imported(self):
        store=self.store();course,pairs=self.checkpoint_fixture(store)
        store.course(7,[11,12],course)
        with self.assertRaisesRegex(storage.StorageError,'completed_course_checkpoint_missing'):
            store.completed_course(7)
        store.bind_course(7,course,pairs)
        self.assertEqual([x['lesson_id'] for x in store.completed_course(7)],[11,12])

    def test_completed_checkpoint_never_uses_latest_or_mixes_new_versions(self):
        store=self.store();course,pairs=self.checkpoint_fixture(store)
        store.bind_course(7,course,pairs)
        for ident in (11,12):store.capture('lesson',7,ident,verified_lesson(ident,'new unbound version'))
        store.capture('course',7,0,{**verified_course(),'html':'new unbound course version'})
        with patch.object(store,'latest',side_effect=AssertionError('must never use latest')):
            payloads=store.completed_course(7)
        self.assertEqual([x['ape']['children'][0]['fields']['html'] for x in payloads],['original','original'])

    def test_checkpoint_requires_verified_exact_owned_captures_and_order(self):
        store=self.store();course,pairs=self.checkpoint_fixture(store)
        bad_course=store.capture('course',7,0,{**verified_course(),'verified':False})
        bad_lesson=store.capture('lesson',7,11,{**verified_lesson(11),'verified':False})
        foreign_lesson=verified_lesson(11);foreign_lesson['parsed']['payload']['source_origin']='https://shop.mv-centr.ru'
        foreign=store.capture('lesson',7,11,foreign_lesson)
        for digest,assignment,code in [(bad_course,pairs,'capture_unverified'),
                (course,[(11,bad_lesson),pairs[1]],'capture_unverified'),
                (course,[(11,foreign),pairs[1]],'identity_mismatch'),
                (course,list(reversed(pairs)),'lesson_order_mismatch'),
                (course,[(11,'0'*64),pairs[1]],'capture_missing')]:
            with self.assertRaisesRegex(storage.StorageError,code):store.bind_course(7,digest,assignment)
        self.assertEqual(store.db.execute('SELECT COUNT(*) FROM course_checkpoints').fetchone()[0],0)
        self.assertEqual(store.summary(),{'pending':1})

    def test_checkpoint_validates_titles_course_and_lesson_identity(self):
        store=self.store();course,pairs=self.checkpoint_fixture(store)
        for field,changed in [('course_id',99),('lesson_id',12),('course_title','Other'),('lesson_title','Other')]:
            lesson=verified_lesson(11);lesson['parsed']['payload'][field]=changed
            digest=store.capture('lesson',7,11,lesson)
            with self.assertRaisesRegex(storage.StorageError,'identity_mismatch'):
                store.bind_course(7,course,[(11,digest),pairs[1]])

    def test_failed_recheck_raw_captures_do_not_create_or_replace_checkpoint(self):
        store=self.store();course,pairs=self.checkpoint_fixture(store)
        # A first failed bookend recheck leaves raw captures but no completed job.
        store.capture('course',7,0,verified_course(ids=(11,12,13)))
        store.mark(7,'review')
        with self.assertRaisesRegex(storage.StorageError,'completed_course_checkpoint_missing'):store.completed_course(7)
        store.bind_course(7,course,pairs)
        # A later incomplete attempt cannot replace an already bound collection.
        store.capture('course',7,0,verified_course(title='Changed unbound title'))
        store.mark(7,'review')
        self.assertEqual([x['course_title'] for x in store.completed_course(7)],['Course','Course'])

    def test_checkpoint_corruption_never_falls_back_to_new_valid_snapshot(self):
        store=self.store();course,pairs=self.checkpoint_fixture(store);store.bind_course(7,course,pairs)
        store.capture('lesson',7,11,verified_lesson(11,'new valid version'))
        store.db.execute('UPDATE captures SET payload=? WHERE digest=?',(zlib.compress(b'{}'),pairs[0][1]));store.db.commit()
        with self.assertRaisesRegex(storage.StorageError,'digest_mismatch'):store.completed_course(7)

    def test_checkpoint_and_ledger_commit_together(self):
        store=self.store();course,pairs=self.checkpoint_fixture(store)
        store.db.execute("CREATE TRIGGER reject_checkpoint BEFORE INSERT ON course_checkpoints BEGIN SELECT RAISE(ABORT,'synthetic failure'); END")
        with self.assertRaises(sqlite3.IntegrityError):store.bind_course(7,course,pairs)
        row=store.db.execute('SELECT source_digest,lesson_ids,state FROM courses WHERE id=7').fetchone()
        self.assertEqual(tuple(row),(None,None,'pending'))
        self.assertEqual(store.db.execute('SELECT COUNT(*) FROM course_checkpoints').fetchone()[0],0)

    def test_changed_lesson_hash_resets_imported_even_if_course_digest_same(self):
        store=self.store();course,pairs=self.checkpoint_fixture(store);store.bind_course(7,course,pairs);store.mark(7,'imported')
        store.bind_course(7,course,pairs);self.assertEqual(store.summary(),{'imported':1})
        changed=store.capture('lesson',7,11,verified_lesson(11,'changed lesson only'))
        store.bind_course(7,course,[(11,changed),pairs[1]])
        self.assertEqual(store.summary(),{'collected':1})
        self.assertEqual(store.completed_course(7)[0]['ape']['children'][0]['fields']['html'],'changed lesson only')

    def test_ledger_checkpoint_mismatch_and_empty_completed_course(self):
        store=self.store();course,pairs=self.checkpoint_fixture(store);store.bind_course(7,course,pairs)
        changed=store.capture('course',7,0,{**verified_course(),'html':'new collection not checkpointed'})
        store.course(7,[11,12],changed)
        with self.assertRaisesRegex(storage.StorageError,'source_mismatch'):store.completed_course(7)
        empty=store.capture('course',7,0,verified_course(ids=()))
        store.bind_course(7,empty,[]);self.assertEqual(store.completed_course(7),[])

    def test_stable_lesson_keeps_fresh_observation_raw_html_and_checkpoint_identity(self):
        store=self.store();store.catalog([{'id':7,'title':'Course'}])
        course=store.capture('course',7,0,verified_course(ids=(11,)))
        historical=uuid_lesson('00000000-0000-0000-0000-000000000001','00000000-0000-0000-0000-000000000002')
        historical_digest=store.capture('lesson',7,11,historical)
        original_blob=bytes(store.db.execute('SELECT payload FROM captures WHERE digest=?',(historical_digest,)).fetchone()[0])
        current=uuid_lesson('00000000-0000-0000-0000-000000000101','00000000-0000-0000-0000-000000000102')
        current['parsed']['settings']=[{'name':'synthetic','value':'fresh settings'}]
        untouched=copy.deepcopy(current)
        stable=store.stable_lesson(7,11,current['parsed'])
        self.assertEqual(stable['payload'],historical['parsed']['payload'])
        self.assertEqual(stable['observed_payload'],current['parsed']['payload'])
        self.assertEqual(stable['settings'],current['parsed']['settings'])
        self.assertEqual(stable['canonicalization'],['ape_unused_ids_reused'])
        self.assertEqual(current,untouched)
        captured={**current,'parsed':stable}
        fresh_digest=store.capture('lesson',7,11,captured)
        self.assertNotEqual(fresh_digest,historical_digest)
        self.assertEqual(store.latest('lesson',7,11),captured)
        raw=store.db.execute('SELECT payload FROM captures WHERE digest=?',(fresh_digest,)).fetchone()[0]
        self.assertEqual(json.loads(zlib.decompress(raw))['html'],current['html'])
        self.assertEqual(json.loads(zlib.decompress(raw))['parsed']['observed_payload'],current['parsed']['payload'])
        self.assertEqual(bytes(store.db.execute('SELECT payload FROM captures WHERE digest=?',(historical_digest,)).fetchone()[0]),original_blob)
        store.bind_course(7,course,[(11,fresh_digest)])
        self.assertEqual(store.completed_course(7),[historical['parsed']['payload']])

    def test_stable_lesson_does_not_canonicalize_real_text_or_media_changes(self):
        store=self.store()
        historical=uuid_lesson('00000000-0000-0000-0000-000000000001','00000000-0000-0000-0000-000000000002',
                               '<a href="https://example.test/first">Original material</a>')
        digest=store.capture('lesson',7,11,historical)
        for markup in ('<a href="https://example.test/first">Updated instructions</a>',
                       '<a href="https://example.test/second">Original material</a>'):
            current=uuid_lesson('00000000-0000-0000-0000-000000000101','00000000-0000-0000-0000-000000000102',markup)
            stable=store.stable_lesson(7,11,current['parsed'])
            self.assertEqual(stable,current['parsed'])
            self.assertNotIn('observed_payload',stable)
            self.assertNotIn('canonicalization',stable)
        self.assertEqual(store.db.execute('SELECT COUNT(*) FROM captures').fetchone()[0],1)
        self.assertEqual(json.loads(zlib.decompress(store.db.execute('SELECT payload FROM captures WHERE digest=?',(digest,)).fetchone()[0])),historical)

    def test_stable_lesson_rejects_foreign_current_source_without_writes(self):
        store=self.store()
        historical=uuid_lesson('00000000-0000-0000-0000-000000000001','00000000-0000-0000-0000-000000000002')
        store.capture('lesson',7,11,historical)
        before=[tuple(row) for row in store.db.execute('SELECT digest,payload FROM captures')]
        for key,value in (('account','mv-centr'),('source_origin','https://shop.mv-centr.ru')):
            current=uuid_lesson('00000000-0000-0000-0000-000000000101','00000000-0000-0000-0000-000000000102')['parsed']
            current['payload'][key]=value
            untouched=copy.deepcopy(current)
            with self.subTest(key=key),self.assertRaisesRegex(storage.StorageError,'source_capture_account_mismatch'):
                store.stable_lesson(7,11,current)
            self.assertEqual(current,untouched)
        self.assertEqual([tuple(row) for row in store.db.execute('SELECT digest,payload FROM captures')],before)

    def test_stable_lesson_rejects_foreign_historical_payload_in_owned_archive(self):
        store=self.store()
        historical=uuid_lesson('00000000-0000-0000-0000-000000000001','00000000-0000-0000-0000-000000000002')
        historical['parsed']['payload']['account']='mv-centr'
        store.capture('lesson',7,11,historical)
        before=[tuple(row) for row in store.db.execute('SELECT digest,payload FROM captures')]
        current=uuid_lesson('00000000-0000-0000-0000-000000000101','00000000-0000-0000-0000-000000000102')['parsed']
        with self.assertRaisesRegex(ImportStop,'canonical_source_account_mismatch'):
            store.stable_lesson(7,11,current)
        self.assertEqual([tuple(row) for row in store.db.execute('SELECT digest,payload FROM captures')],before)


if __name__=='__main__':unittest.main()

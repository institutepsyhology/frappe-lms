"""Synthetic read-only archive and localhost-only dashboard tests."""
from contextlib import closing
from datetime import datetime, timezone
import http.client
import json
from pathlib import Path
import shutil
import sqlite3
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
import uuid

import progress_view as mod


class Tests(unittest.TestCase):
    def setUp(self):
        self.parent = Path(__file__).resolve().parents[3] / '.tmp-mastervision-progress-tests'
        self.parent.mkdir(exist_ok=True)
        self.folder = self.parent / ('fixture-' + uuid.uuid4().hex)
        self.jobs = self.folder / 'exports/lesson-content/mastervision-migration/jobs'
        self.jobs.mkdir(parents=True)
        self.path = self.jobs.parent / 'mastervision-migration.sqlite'
        self.addCleanup(self.cleanup)
        with closing(sqlite3.connect(self.path)) as db, db:
            db.executescript('''CREATE TABLE meta(account,origin,site); CREATE TABLE courses(id,state,lesson_ids);
              CREATE TABLE course_checkpoints(lesson_digests);CREATE TABLE errors(stage,consecutive);
              CREATE TABLE events(id,at,stage,course,lesson,status);''')
            db.execute('INSERT INTO meta VALUES(?,?,?)', ('mastervision','https://shop.mastervision.su','my-lk.mastervision.su'))
            db.executemany('INSERT INTO courses VALUES(?,?,?)', [(1,'imported','[11,12]'),(2,'review','[21]'),(3,'imported','[]')])
            db.execute('INSERT INTO course_checkpoints VALUES(?)', (json.dumps([[11,'digest'],[12,'digest']]),))
            db.execute('INSERT INTO events VALUES(1,?,?,?,?,?)', ('2026-11-13T07:00:00+00:00','import',1,12,'lesson_created'))

    def cleanup(self):
        if self.folder.parent.resolve() != self.parent.resolve() or not self.folder.name.startswith('fixture-'):
            raise RuntimeError('unsafe_fixture_cleanup')
        shutil.rmtree(self.folder)

    def job(self, created='2026-11-13T06:00:00+00:00', **overrides):
        ident = 'job-' + uuid.uuid4().hex
        data = {'version':1,'job_id':ident,'workspace':str(self.folder.resolve()),'source_commit':'a'*40,
                'status':'running','pid':123,'created_at_utc':created,'started_at_utc':created,'finished_at_utc':None,
                'Cookie':'PRIVATE_COOKIE','arguments':['PRIVATE_ARGUMENT']}
        data.update(overrides)
        path = self.jobs / (ident + '.json')
        path.write_text(json.dumps(data), encoding='utf-8')
        return path

    def test_snapshot_counts_read_only_and_only_metadata(self):
        before = self.path.read_bytes()
        self.job()
        checker = Mock(return_value=True)
        data = mod.snapshot(self.path, checker)
        self.assertEqual(data['courses'], {'imported':2,'review':1})
        self.assertEqual(data['imported_lessons'],2)
        self.assertEqual(data['source_lessons'],2)
        self.assertTrue(data['worker']['running'])
        self.assertEqual(data['last_event']['course'],1)
        self.assertEqual(data['last_event']['lesson'],12)
        self.assertIn('10:00:00',data['last_event']['at_msk'])
        self.assertEqual(before,self.path.read_bytes())
        self.assertNotIn('PRIVATE',json.dumps(data))
        checker.assert_called_once_with(123,'2026-11-13T06:00:00+00:00')

    def test_completed_job_with_reused_live_pid_is_not_running(self):
        self.job(status='completed',finished_at_utc='2026-11-13T07:00:00+00:00')
        checker=Mock(return_value=True)
        result=mod.worker_status(self.jobs,checker)
        self.assertFalse(result['running']);self.assertEqual(result['state'],'completed')
        self.assertIsNone(result['pid']);checker.assert_not_called()

    def test_audio_summary_contains_counts_only_and_checks_source_binding(self):
        directory = self.path.parent
        inventory = {'version':1,'account':'mastervision','origin':'https://shop.mastervision.su',
                     'files':[{'url_sha256':'a'*64,'size_bytes':100,'source':'PRIVATE'}]}
        index = {'version':1,'account':'mastervision','origin':'https://shop.mastervision.su','site':'my-lk.mastervision.su',
                 'files':{'a'*64:{'url_sha256':'a'*64,'size':100,'basename':'PRIVATE'}}}
        for name, data in (('audio-inventory.json',inventory),('audio-stage-index.json',index)):
            (directory/name).write_text(json.dumps(data),encoding='utf-8')
        self.assertEqual(mod.audio_progress(directory), {'staged':1,'registered':0,'total':1,'bytes_staged':100,'bytes_total':100})
        registered = {**index, 'files':{'a'*64:{'size':100}}}
        (directory/'audio-files-index.json').write_text(json.dumps(registered),encoding='utf-8')
        self.assertEqual(mod.audio_progress(directory)['registered'],1)
        index['account'] = 'mv-centr'
        (directory/'audio-stage-index.json').write_text(json.dumps(index),encoding='utf-8')
        with self.assertRaises(ValueError): mod.audio_progress(directory)

    def test_invalid_ports_do_not_open_sockets(self):
        for value in (-1,65536,True,'61929'):
            with self.subTest(value=value), self.assertRaises(ValueError): mod.make_server(self.path, port=value)

    def test_stale_running_pid_is_not_reported_running(self):
        self.job()
        checker=Mock(return_value=False)
        result=mod.worker_status(self.jobs,checker)
        self.assertFalse(result['running']);self.assertEqual(result['state'],'stopped')
        self.assertIsNone(result['pid'])

    def test_latest_job_uses_creation_time_not_file_order(self):
        self.job(created='2026-11-13T07:00:00+00:00',status='completed')
        self.job(created='2026-11-13T06:00:00+00:00')
        checker=Mock(return_value=True)
        self.assertEqual(mod.worker_status(self.jobs,checker)['state'],'completed')
        checker.assert_not_called()

    def test_starting_and_missing_jobs_never_claim_running(self):
        checker=Mock(return_value=True)
        self.assertEqual(mod.worker_status(self.jobs,checker)['state'],'none')
        self.job(status='starting',pid=None,started_at_utc=None)
        self.assertEqual(mod.worker_status(self.jobs,checker)['state'],'starting')
        checker.assert_not_called()

    def test_foreign_workspace_or_untrusted_commit_job_ignored(self):
        self.job(workspace='foreign-workspace')
        self.job(source_commit='<script>PRIVATE</script>')
        checker=Mock(return_value=True)
        self.assertEqual(mod.worker_status(self.jobs,checker)['state'],'none')
        checker.assert_not_called()

    def test_foreign_source_identity_rejected_before_process_check(self):
        self.job()
        with closing(sqlite3.connect(self.path)) as db, db:db.execute("UPDATE meta SET account='mv-centr'")
        checker=Mock(return_value=True)
        with self.assertRaisesRegex(ValueError,'status_account_mismatch'):mod.snapshot(self.path,checker)
        checker.assert_not_called()

    def test_unknown_event_text_is_not_exposed(self):
        with closing(sqlite3.connect(self.path)) as db, db:db.execute("UPDATE events SET status='<script>PRIVATE</script>'")
        data=mod.snapshot(self.path)
        self.assertEqual(data['last_event']['status'],'unknown')
        self.assertNotIn('PRIVATE',json.dumps(data))

    def test_two_local_routes_no_file_serving_or_cors(self):
        self.job(status='completed')
        with mod.make_server(self.path,lambda *args:False) as server:
            self.assertEqual(server.server_address[0],'127.0.0.1')
            thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
            try:
                for route,expected in (('/',200),('/status.json',200),('/../mastervision-migration.sqlite',404),('/status.json?path=secret',404)):
                    connection=http.client.HTTPConnection(*server.server_address,timeout=3)
                    connection.request('GET',route);response=connection.getresponse();body=response.read();connection.close()
                    self.assertEqual(response.status,expected)
                    self.assertEqual(response.getheader('Cache-Control'),'no-store')
                    self.assertIsNone(response.getheader('Access-Control-Allow-Origin'))
                    self.assertNotIn(b'PRIVATE',body)
                    if route=='/':
                        self.assertIn('Перенос Master Vision',body.decode())
                        self.assertIn('textContent',body.decode());self.assertNotIn('innerHTML',body.decode())
                    if route=='/status.json':self.assertEqual(json.loads(body)['imported_lessons'],2)
            finally:server.shutdown();thread.join(timeout=3)

    def test_http_failures_only_return_fixed_diagnostic(self):
        with mod.make_server(self.path) as server, patch.object(mod,'snapshot',side_effect=ValueError('PRIVATE')):
            thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
            try:
                connection=http.client.HTTPConnection(*server.server_address,timeout=3)
                connection.request('GET','/status.json');response=connection.getresponse()
                self.assertEqual(json.loads(response.read()),{'status':'unavailable'});connection.close()
            finally:server.shutdown();thread.join(timeout=3)

    def test_process_query_never_uses_kill_and_invalid_pids_are_safe(self):
        with patch.object(mod.os,'kill',side_effect=AssertionError('must not call kill')):
            for pid in (None,False,0,-1,2**40):self.assertFalse(mod.windows_process_matches(pid,'2026-11-13T06:00:00+00:00'))

    def test_windows_process_check_requires_alive_python_and_matching_creation_time(self):
        import ctypes
        started='2026-11-13T06:00:00+00:00'
        for offset,exit_code,image,expected in ((0,259,'python.exe',True),(11,259,'python.exe',False),
                                               (0,0,'python.exe',False),(0,259,'other.exe',False)):
            kernel=SimpleNamespace(OpenProcess=Mock(return_value=99),CloseHandle=Mock(return_value=1))
            def code(handle,pointer):pointer._obj.value=exit_code;return 1
            def times(handle,creation,*unused):
                ticks=int((mod.timestamp(started).timestamp()+offset+11644473600)*10**7)
                creation._obj.dwHighDateTime=ticks>>32;creation._obj.dwLowDateTime=ticks&0xffffffff
                return 1
            def name(handle,flags,buffer,size):buffer.value=image;return 1
            kernel.GetExitCodeProcess=Mock(side_effect=code)
            kernel.GetProcessTimes=Mock(side_effect=times)
            kernel.QueryFullProcessImageNameW=Mock(side_effect=name)
            with self.subTest(offset=offset,exit_code=exit_code,image=image), \
                    patch.object(mod,'os',SimpleNamespace(name='nt')), \
                    patch.object(ctypes,'WinDLL',return_value=kernel,create=True):
                self.assertEqual(mod.windows_process_matches(123,started),expected)
            kernel.OpenProcess.assert_called_once_with(0x1000,False,123)
            kernel.CloseHandle.assert_called_once_with(99)

    def test_foreign_host_cannot_read_local_metadata(self):
        with mod.make_server(self.path) as server:
            thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
            try:
                connection=http.client.HTTPConnection(*server.server_address,timeout=3)
                connection.request('GET','/status.json',headers={'Host':'foreign.example'})
                response=connection.getresponse();self.assertEqual(response.status,403)
                self.assertEqual(response.read(),b'Forbidden');connection.close()
            finally:server.shutdown();thread.join(timeout=3)


if __name__=='__main__':unittest.main()

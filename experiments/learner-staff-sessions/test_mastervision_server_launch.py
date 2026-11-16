"""Synthetic tests for the private key handoff; no live AVO/server calls."""
from contextlib import redirect_stdout,nullcontext
import io
import json
import os
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import uuid

import launch_mastervision_archive as client
import server_archive_job as server

KEY='SYNTHETIC_MASTER_VISION_KEY_NEVER_LOG'
REVISION='a'*40


def success(**changes):
    return dict({'status':'started','site':client.SITE,'account':'mastervision',
        'worker_pid':12345,'key_saved':False},**changes)


class LauncherTests(unittest.TestCase):
    def test_key_goes_only_to_stdin_and_fixed_mv_destination(self):
        def fake(args,**kwargs):
            self.assertNotIn(KEY,repr(args))
            self.assertNotIn('env',kwargs)
            self.assertEqual(json.loads(kwargs['input']),{'key':KEY})
            self.assertIn('StrictHostKeyChecking=yes',args)
            self.assertIn(client.SITE,repr(args))
            self.assertNotIn('my-lk.mv-centr.ru',repr(args))
            return SimpleNamespace(returncode=0,stdout=json.dumps(success()).encode())
        with patch.object(client.subprocess,'run',side_effect=fake):
            self.assertEqual(client.start(REVISION,KEY),success())

    def test_wrong_account_or_saved_key_response_is_not_success(self):
        for changes in ({'account':'mv-centr'},{'site':'my-lk.mv-centr.ru'},
                {'key_saved':True},{'worker_pid':True},{'status':'stopped'}):
            result=SimpleNamespace(returncode=0,stdout=json.dumps(success(**changes)).encode())
            with patch.object(client.subprocess,'run',return_value=result),self.assertRaises(client.LaunchError):
                client.start(REVISION,KEY)

    def test_connection_errors_never_echo_key(self):
        with patch.object(client.subprocess,'run',side_effect=OSError(KEY)):
            with self.assertRaises(client.LaunchError) as caught:client.start(REVISION,KEY)
        self.assertNotIn(KEY,str(caught.exception))

    def test_invalid_revision_or_key_never_connects(self):
        with patch.object(client.subprocess,'run') as network:
            for revision in ('..','a'*39,'a'*40+';bad'):
                with self.assertRaises(client.LaunchError):client.start(revision,KEY)
            for key in ('','some key','https://shop.mv-centr.ru/?key='+KEY):
                with self.assertRaises(client.LaunchError):client.start(REVISION,key)
            network.assert_not_called()

    def test_server_key_reader_is_bounded_and_strict(self):
        self.assertEqual(server.read_key(io.BytesIO(json.dumps({'key':KEY}).encode())),KEY)
        for raw in (b'x'*4097,b'{',b'{"key":1}',json.dumps({'key':KEY,'extra':True}).encode()):
            with self.assertRaises(server.JobError):server.read_key(io.BytesIO(raw))

    def test_wrong_server_profile_rejected_before_runtime_import(self):
        with patch.dict(os.environ,{'AVO_ARCHIVE_ACCOUNT':'mv-centr'}):
            with self.assertRaises(server.JobError) as caught:server.bound_runtime()
        self.assertEqual(str(caught.exception),'wrong_account')

    def test_duplicate_start_does_not_clobber_active_status(self):
        with patch.object(server.sys,'argv',['server_archive_job.py','--start']), \
                patch.object(server,'verify_release',return_value=REVISION), \
                patch.object(server,'launch_worker',side_effect=server.JobError('already_running')), \
                patch.object(server,'write_status') as writer,redirect_stdout(io.StringIO()) as output:
            self.assertEqual(server.main(),1)
            writer.assert_not_called()
        self.assertEqual(json.loads(output.getvalue())['error_code'],'already_running')

    def test_detached_process_key_is_pipe_only(self):
        parent=Path(__file__).resolve().parents[3]/'exports'
        folder=parent/('.synthetic-mv-launch-'+uuid.uuid4().hex);folder.mkdir()
        pipe=io.BytesIO()
        captured=[]
        class Pipe:
            def write(self,data):captured.append(data)
            def close(self):pass
        def popen(args,**kwargs):
            self.assertNotIn(KEY,repr(args));self.assertNotIn('env',kwargs)
            self.assertIs(kwargs['start_new_session'],True)
            self.assertIs(kwargs['close_fds'],True)
            (folder/'server-status.json').write_text(json.dumps({'worker_pid':123,'status':'collecting'}))
            return SimpleNamespace(pid=123,stdin=Pipe(),poll=lambda:None)
        try:
            with patch.object(server,'BASE',folder),patch.object(server,'JOB',folder), \
                    patch.object(server,'private_directory',lambda p:p), \
                    patch.object(server,'lock',lambda p:nullcontext()), \
                    patch.object(server,'__file__',str(folder/('release-'+REVISION)/'server_archive_job.py')), \
                    patch.object(server.sys,'stdin',SimpleNamespace(buffer=io.BytesIO(json.dumps({'key':KEY}).encode()))), \
                    patch.object(server.subprocess,'Popen',side_effect=popen), \
                    patch.object(server.os,'O_NOFOLLOW',getattr(os,'O_NOFOLLOW',0),create=True):
                self.assertEqual(server.launch_worker()['worker_pid'],123)
            self.assertEqual(json.loads(b''.join(captured)),{'key':KEY})
            self.assertNotIn(KEY,(folder/'worker.log').read_text())
        finally:
            for name in ('server-status.json','worker.log'):(folder/name).unlink(missing_ok=True)
            folder.rmdir()

    def test_release_manifest_checks_every_source_file(self):
        import hashlib
        parent=Path(__file__).resolve().parents[3]/'exports'
        root=parent/('.synthetic-mv-release-'+uuid.uuid4().hex);root.mkdir()
        folder=root/('release-'+REVISION);folder.mkdir()
        source=folder/'server_archive_job.py';source.write_bytes(b'SYNTHETIC_PUBLIC_SOURCE')
        manifest={'revision':REVISION,'files':{'server_archive_job.py':hashlib.sha256(source.read_bytes()).hexdigest()}}
        (folder/'manifest.json').write_text(json.dumps(manifest))
        try:
            with patch.object(server,'__file__',str(source)),patch.object(server,'RELEASE_FILES',('server_archive_job.py',)):
                self.assertEqual(server.verify_release(),REVISION)
                source.write_bytes(b'UNREVIEWED_CHANGE')
                with self.assertRaises(server.JobError):server.verify_release()
        finally:
            source.unlink();(folder/'manifest.json').unlink();folder.rmdir();root.rmdir()


if __name__=='__main__':unittest.main()

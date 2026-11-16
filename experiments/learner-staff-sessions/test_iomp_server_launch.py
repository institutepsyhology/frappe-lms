"""Synthetic IOMP startup isolation; no keys, network, server or GUI actions."""
from contextlib import redirect_stdout
import io
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import install_mastervision_archive as installer
import launch_mastervision_archive as client


HERE = Path(__file__).resolve().parent
REVISION = 'a' * 40
KEY = 'SYNTHETIC_IOMP_API_KEY_NEVER_LOG'


def child(script, account='iomp', source_account=None):
    env = os.environ.copy()
    env['AVO_SERVER_ARCHIVE_ACCOUNT'] = account
    env['PYTHONUTF8'] = '1'
    if source_account is None:
        env.pop('AVO_ARCHIVE_ACCOUNT', None)
    else:
        env['AVO_ARCHIVE_ACCOUNT'] = source_account
    result = subprocess.run([sys.executable, '-B', '-c', script], cwd=HERE, env=env,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=25)
    if result.returncode:
        raise AssertionError('Synthetic subprocess failed:\n' + result.stderr[-5000:])
    return json.loads(result.stdout)


def response(site='my-lk.iomp.ru', account='iomp'):
    return {'status': 'started', 'site': site, 'account': account,
            'worker_pid': 12345, 'key_saved': False}


class IompLauncherTests(unittest.TestCase):
    def test_fixed_iomp_target_and_nonsecret_selector_are_command_only(self):
        args = client.command(REVISION, 'iomp')
        remote = shlex.split(args[-1])
        self.assertEqual(remote[remote.index('-e') + 1], 'AVO_SERVER_ARCHIVE_ACCOUNT=iomp')
        self.assertIn('StrictHostKeyChecking=yes', args)
        self.assertIn('/home/frappe/frappe-bench/sites/my-lk.iomp.ru/private/avo-api-archive/'
                      'release-' + REVISION + '/server_archive_job.py', remote)
        self.assertNotIn('my-lk.mastervision.su', args[-1])
        self.assertNotIn(KEY, repr(args))

    def test_key_goes_to_stdin_only_and_iomp_ack_is_required(self):
        def fake(args, **kwargs):
            self.assertNotIn(KEY, repr(args))
            self.assertNotIn('env', kwargs)
            self.assertEqual(json.loads(kwargs['input']), {'key': KEY})
            return SimpleNamespace(returncode=0, stdout=json.dumps(response()).encode())
        with patch.object(client.subprocess, 'run', side_effect=fake):
            self.assertEqual(client.start(REVISION, KEY, 'iomp'), response())
        for site, account in (('my-lk.mastervision.su', 'mastervision'),
                              ('my-lk.mv-centr.ru', 'mv-centr'), ('my-lk.iomp.ru', 'mastervision')):
            result = SimpleNamespace(returncode=0, stdout=json.dumps(response(site, account)).encode())
            with patch.object(client.subprocess, 'run', return_value=result), self.assertRaises(client.LaunchError):
                client.start(REVISION, KEY, 'iomp')

    def test_unknown_or_injected_accounts_never_connect(self):
        with patch.object(client.subprocess, 'run') as network:
            for account in ('mv-centr', '../iomp', 'iomp;bad', '', None):
                with self.assertRaises(client.LaunchError):
                    client.start(REVISION, KEY, account)
            network.assert_not_called()

    def test_default_mastervision_still_selects_only_mastervision(self):
        remote = shlex.split(client.command(REVISION)[-1])
        self.assertEqual(remote[remote.index('-e') + 1], 'AVO_SERVER_ARCHIVE_ACCOUNT=mastervision')
        self.assertIn('my-lk.mastervision.su', ' '.join(remote))
        self.assertNotIn('my-lk.iomp.ru', ' '.join(remote))

    def test_server_startup_fixes_iomp_paths_without_importing_core_or_key(self):
        result = child('''
import json,sys,os
import server_archive_job as job
assert 'server_archive_sink' not in sys.modules
assert job.ACCOUNT=='iomp'
assert job.SITE=='my-lk.iomp.ru'
assert job.API_ORIGIN=='https://shop.iomp.ru'
assert job.JOB.as_posix()=='/home/frappe/frappe-bench/sites/my-lk.iomp.ru/private/avo-api-archive/job-20261116'
os.environ['AVO_SERVER_ARCHIVE_ACCOUNT']='mastervision'
assert job.ACCOUNT=='iomp'
print(json.dumps({'fixed':True}))
''')
        self.assertTrue(result['fixed'])

    def test_bound_runtime_selects_iomp_before_core_and_reads_existing_iomp_key(self):
        result = child('''
import json,sys,types
from cryptography.fernet import Fernet
import server_archive_job as job
key=Fernet.generate_key().decode()
events=[]
fake=types.SimpleNamespace(local=types.SimpleNamespace(site='my-lk.iomp.ru'),
 conf={'encryption_key':key},init=lambda **kwargs:events.append(kwargs),destroy=lambda:None,
 get_site_path=lambda *args:'/home/frappe/frappe-bench/sites/my-lk.iomp.ru/private/avo-ingest')
sys.modules['frappe']=fake
profile=job.bound_runtime()
import private_link_storage as storage
encrypted=storage._crypt(10,b'SYNTHETIC_ONLY')
assert storage._crypt(10,encrypted,decrypt=True)==b'SYNTHETIC_ONLY'
assert profile.account=='iomp' and profile.site==job.SITE
assert events==[{'site':'my-lk.iomp.ru'}]
print(json.dumps({'bound':True}))
''')
        self.assertTrue(result['bound'])

    def test_wrong_source_profile_and_unknown_server_account_fail_closed(self):
        result = child('''
import json
import server_archive_job as job
try:job.bound_runtime()
except job.JobError as e:rejected=str(e)=='wrong_account'
else:rejected=False
print(json.dumps({'rejected':rejected}))
''', source_account='mastervision')
        self.assertTrue(result['rejected'])
        result = child('''
import json
try:import server_archive_job
except Exception as e:rejected=str(e)=='wrong_account'
else:rejected=False
print(json.dumps({'rejected':rejected}))
''', account='mv-centr')
        self.assertTrue(result['rejected'])

    def test_iomp_contact_links_accept_only_iomp_shop_and_matching_uid(self):
        result = child('''
import os,json
os.environ['AVO_ARCHIVE_ACCOUNT']='iomp'
import collect_personal_links as links
url='https://shop.iomp.ru/personal/auth/secure-login?uid=10&vc=SYNTHETIC'
assert links.verified_link(10,{'link_personal_auth':url})[0]==url
rejected=0
for bad in (url.replace('iomp.ru','mastervision.su'),url.replace('iomp.ru','mv-centr.ru'),url.replace('uid=10','uid=11')):
 try:links.verified_link(10,{'link_personal_auth':bad})
 except links.CollectionError:rejected+=1
print(json.dumps({'rejected':rejected}))
''')
        self.assertEqual(result['rejected'], 3)

    def test_installer_selects_iomp_by_startup_configuration_and_checks_readback(self):
        public = {'revision': REVISION, 'files': {}}
        def fake(args, **kwargs):
            remote = shlex.split(args[-1])
            self.assertEqual(remote[remote.index('-e') + 1], 'AVO_SERVER_ARCHIVE_ACCOUNT=iomp')
            self.assertEqual(json.loads(kwargs['input']), public)
            self.assertNotIn('env', kwargs)
            self.assertNotIn(KEY, repr(args))
            report = {'installed': True, 'site': 'my-lk.iomp.ru', 'revision': REVISION,
                      'files_verified': len(installer.FILES)}
            return SimpleNamespace(returncode=0, stdout=json.dumps(report).encode())
        with patch.object(installer, 'payload', return_value=public), \
             patch.object(installer.subprocess, 'run', side_effect=fake):
            self.assertEqual(installer.install(REVISION, 'iomp')['site'], 'my-lk.iomp.ru')
        wrong = SimpleNamespace(returncode=0, stdout=json.dumps({'installed': True,
            'site': 'my-lk.mastervision.su', 'revision': REVISION, 'files_verified': 8}).encode())
        with patch.object(installer, 'payload', return_value=public), \
             patch.object(installer.subprocess, 'run', return_value=wrong), self.assertRaises(RuntimeError):
            installer.install(REVISION, 'iomp')

    def test_installer_rejects_unknown_account_before_payload_or_network(self):
        with patch.object(installer, 'payload') as payload, patch.object(installer.subprocess, 'run') as network:
            with self.assertRaises(ValueError):
                installer.install(REVISION, '../iomp')
            payload.assert_not_called()
            network.assert_not_called()

    def test_cli_routes_to_iomp_without_opening_a_real_window(self):
        with patch.object(sys, 'argv', ['launch', '--release', REVISION, '--account', 'iomp']), \
             patch.object(client, 'command') as command, patch.object(client, 'graphical') as window:
            client.main()
        command.assert_called_once_with(REVISION, 'iomp')
        window.assert_called_once_with(REVISION, 'iomp')


if __name__ == '__main__':
    unittest.main()

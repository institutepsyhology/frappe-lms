"""Synthetic release guards; no Docker, network, Frappe, or real site data."""
import datetime as dt
import contextlib
import importlib.util
import json
from pathlib import Path
import tarfile
import tempfile
import shutil
import unittest
import uuid
from unittest.mock import patch

HERE = Path(__file__).resolve().parent


def load(name):
    spec = importlib.util.spec_from_file_location('private_test_' + name, HERE / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


release = load('release')
context = load('create_context')


@contextlib.contextmanager
def fixture_directory():
    # Python 3.12's mode-0700 mkdtemp ACL cannot be reopened by this Windows
    # restricted token. Public synthetic fixtures can inherit normal temp ACLs.
    parent = Path(tempfile.gettempdir()).resolve(strict=True)
    folder = parent / ('private-access-fixture-' + uuid.uuid4().hex)
    folder.mkdir()
    try:
        yield str(folder)
    finally:
        if folder.parent.resolve(strict=True) != parent or not folder.name.startswith('private-access-fixture-'):
            raise RuntimeError('unsafe_fixture_cleanup')
        shutil.rmtree(folder)


class BackupTests(unittest.TestCase):
    def setUp(self):
        self.temp = fixture_directory()
        self.base = Path(self.temp.__enter__())
        self.addCleanup(self.temp.__exit__, None, None, None)
        self.folder = self.base / 'backups' / 'contact-card-20261112T120000000000Z'
        self.folder.mkdir(parents=True)
        self.path = self.folder / 'manifest.json'
        self.now = dt.datetime(2026, 11, 12, 12, 0, tzinfo=dt.timezone.utc)
        self.report = {'directory': str(self.folder), 'release': release.RELEASE,
                       'baseline_image': release.BASELINE, 'prepared_at_utc': self.now.isoformat(), 'sites': []}
        for site in release.SITES:
            directory = self.folder / site
            directory.mkdir()
            files = {}
            for name in release.BACKUP_FILES:
                file = directory / name
                file.write_bytes(b'synthetic fixture only')
                files[name] = {'bytes': file.stat().st_size, 'sha256': release.digest(file)}
            self.report['sites'].append({'site': site, 'files': files, 'database_bytes': 22,
                                         'gzip_verified': True, 'key_saved': True})
        self.write()

    def write(self):
        self.path.write_text(json.dumps(self.report), encoding='utf-8')

    def verify(self):
        # POSIX ownership is separately tested; fixtures also run on Windows.
        with patch.object(release, 'private_path'):
            return release.validate_backup(self.path, base=self.base, now=self.now)

    def test_three_sites_valid(self):
        self.assertEqual(len(self.verify()['sites']), 3)

    def test_stale_and_future_backups_rejected(self):
        for offset in (dt.timedelta(hours=-3), dt.timedelta(minutes=5)):
            self.report['prepared_at_utc'] = (self.now + offset).isoformat()
            self.write()
            with self.assertRaisesRegex(RuntimeError, 'not_fresh'):
                self.verify()

    def test_other_release_baseline_and_missing_site_rejected(self):
        for key, value, reason in [('release', 'other', 'release_mismatch'),
                                    ('baseline_image', 'sha256:' + '0' * 64, 'release_mismatch'),
                                    ('sites', self.report['sites'][:-1], 'sites_mismatch')]:
            original = self.report[key]
            self.report[key] = value; self.write()
            with self.assertRaisesRegex(RuntimeError, reason):
                self.verify()
            self.report[key] = original

    def test_mutated_backup_rejected(self):
        (self.folder / release.SITES[0] / 'database.sql.gz').write_bytes(b'different fixture')
        with self.assertRaisesRegex(RuntimeError, 'file_changed'):
            self.verify()

    def test_requires_explicit_latest_backup(self):
        other = self.base / 'backups' / 'contact-card-20261112T120001000000Z'
        other.mkdir(); (other / 'manifest.json').write_text('{}')
        with self.assertRaisesRegex(RuntimeError, 'not_latest'):
            self.verify()

    def test_rejects_unverified_gzip(self):
        self.report['sites'][0]['gzip_verified'] = False; self.write()
        with self.assertRaisesRegex(RuntimeError, 'flags_invalid'):
            self.verify()

    def test_posix_private_ownership_mode_and_symlink(self):
        class FakePath:
            def __init__(self, *, uid=0, mode=0o100600, link=False):
                self.uid, self.mode, self.link = uid, mode, link
            def is_symlink(self): return self.link
            def stat(self):
                return type('Stat', (), {'st_uid': self.uid, 'st_mode': self.mode, 'st_size': 1})()
        release.private_path(FakePath())
        for file in (FakePath(uid=1000), FakePath(mode=0o100644), FakePath(link=True)):
            with self.assertRaises(RuntimeError): release.private_path(file)


class ContextTests(unittest.TestCase):
    def test_deterministic_committed_allowlist_and_revision(self):
        with fixture_directory() as temp:
            root = Path(temp); repo = root / 'repo'; repo.mkdir()
            commit = '1' * 40
            calls = []
            def git(repo, *args):
                calls.append(args)
                if args[0] == 'rev-parse': return commit.encode()
                name = args[1].split(':', 1)[1]
                if name.endswith('/Dockerfile'): return (HERE / 'Dockerfile').read_bytes().replace(b'\r\n', b'\n')
                return ('committed ' + name + '\n').encode()
            with patch.object(context, 'git_bytes', side_effect=git):
                first = context.create(root / 'one', repo)
                second = context.create(root / 'two', repo)
            self.assertEqual(first, second)
            with tarfile.open(root / 'one' / 'overlay.tar') as archive:
                self.assertEqual(archive.getnames(), list(context.FILES))
                self.assertTrue(all(item.mtime == 0 for item in archive.getmembers()))
            self.assertIn(('ARG SOURCE_REVISION=' + commit).encode(), (root / 'one' / 'Dockerfile').read_bytes())
            self.assertEqual(first['source_revision'], commit)
            self.assertFalse(any('editorHeading' in str(call) for call in calls))

    def test_refuses_context_inside_checkout_or_existing(self):
        with fixture_directory() as temp:
            root = Path(temp); repo = root / 'repo'; repo.mkdir()
            with self.assertRaisesRegex(ValueError, 'outside_checkout'):
                context.create(repo / 'context', repo)
            existing = root / 'existing'; existing.mkdir()
            with self.assertRaisesRegex(ValueError, 'destination_exists'):
                context.create(existing, repo)


class ActivationTests(unittest.TestCase):
    def fake(self):
        class FakeModule:
            BENCH = '/bench'
            BACKEND = 'backend'
            def __init__(self): self.commands = []; self.main_called = False
            def run(self, args, **kwargs):
                self.commands.append(args)
                if args == ['hostname']: return 'spb-3-vm-t6fa'
                if args[:3] == ['docker', 'image', 'inspect']:
                    return json.dumps([{'Id': 'sha256:' + '2' * 64, 'Config': {'Labels': {
                        'ru.mvcentr.baseline': release.BASELINE,
                        'ru.mvcentr.release': release.RELEASE,
                        'org.opencontainers.image.revision': '1' * 40,
                        'org.opencontainers.image.source': 'https://github.com/institutepsyhology/frappe-lms',
                    }}}])
                return json.dumps({'site': args[-1], 'cache_cleared': True, 'schema_changed': False})
            def main(self):
                self.main_called = True
                self.setup_sites()
                return 0
        return FakeModule()

    def test_immutable_image_and_cache_only_setup(self):
        module = self.fake()
        with patch.object(release, 'load', return_value=module), patch.object(release, 'validate_backup'), \
                patch.object(release.os, 'geteuid', return_value=0, create=True):
            self.assertEqual(release.activate('sha256:' + '2' * 64, '/explicit/manifest.json', '1' * 40), 0)
        self.assertEqual(module.OLD, release.BASELINE)
        self.assertEqual(module.NEW, module.TAG)
        self.assertTrue(module.main_called)
        cache_calls = [args for args in module.commands if args[:2] == ['docker', 'exec']]
        self.assertEqual(len(cache_calls), 3)
        for args in cache_calls:
            code = args[args.index('-c') + 1]
            self.assertIn('frappe.clear_cache();translate.clear_cache()', code)
            self.assertNotIn('ensure_', code)
            self.assertNotIn('.commit(', code)

    def test_bad_revision_or_image_provenance_stops_before_activation(self):
        for image, revision, error in [('company-lms:mutable', '1' * 40, 'candidate_image_invalid'),
                                        ('sha256:' + '2' * 64, 'bad', 'source_revision_invalid'),
                                        ('sha256:' + '2' * 64, '3' * 40, 'provenance_mismatch')]:
            module = self.fake()
            with patch.object(release, 'load', return_value=module), patch.object(release, 'validate_backup'), \
                    patch.object(release.os, 'geteuid', return_value=0, create=True):
                with self.assertRaisesRegex(RuntimeError, error):
                    release.activate(image, '/explicit/manifest.json', revision)
            self.assertFalse(module.main_called)

    def test_wrong_host_stops(self):
        module = self.fake()
        original = module.run
        module.run = lambda args, **kwargs: 'other-host' if args == ['hostname'] else original(args, **kwargs)
        with patch.object(release, 'load', return_value=module), \
                patch.object(release.os, 'geteuid', return_value=0, create=True):
            with self.assertRaisesRegex(RuntimeError, 'unexpected_host_or_user'):
                release.activate('sha256:' + '2' * 64, '/explicit/manifest.json', '1' * 40)
        self.assertFalse(module.main_called)


if __name__ == '__main__':
    unittest.main()

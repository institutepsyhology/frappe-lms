"""Committed long-image overlay and stronger fixed layer budget; fake I/O only."""
import importlib.util
import json
from pathlib import Path
import tarfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from test_backend_release import directory

HERE = Path(__file__).resolve().parent


def load(name):
    spec = importlib.util.spec_from_file_location('long_image_test_' + name, HERE / (name + '.py'))
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module); return module


profile = load('release_long_images')
context, release = profile.context, profile.release
REVISION, CANDIDATE = '1' * 40, 'sha256:' + '2' * 64


def git(repo, *args):
    if args[0] == 'rev-parse': return REVISION.encode()
    filename = args[1].split(':', 1)[1]
    return ((HERE / 'create_long_image_context.py').read_bytes().replace(b'\r\n', b'\n')
            if filename == context.GENERATOR else ('committed ' + filename + '\n').encode())


class LongImageReleaseTests(unittest.TestCase):
    def package(self, root):
        repo = root / 'repo'; repo.mkdir()
        with patch.object(context, 'git_bytes', side_effect=git):
            report = context.create(root / 'context', repo, REVISION)
        return root / 'context/source-manifest.json', report

    def fake(self):
        layers = ['layer-' + str(i) for i in range(49)]
        files = {name: 'a' * 64 for name in context.FILES}
        report = {'source_revision': REVISION, 'files': files, 'generator_sha256': 'b' * 64}
        labels = {'org.opencontainers.image.source': context.SOURCE, 'org.opencontainers.image.revision': REVISION,
                  'ru.mvcentr.baseline': context.BASELINE, 'ru.mvcentr.release': context.RELEASE,
                  'ru.mvcentr.sources-sha256': context.sources_digest(files),
                  'ru.mvcentr.generator-sha256': report['generator_sha256']}
        image = {'Id': CANDIDATE, 'RootFS': {'Layers': layers + ['new-layer']}, 'Config': {'Labels': labels}}
        shared = SimpleNamespace(SITES=('one', 'two', 'three'), prepare=Mock(return_value=0),
                                 activate=Mock(return_value=0), validate_backup=Mock())
        def run(args, **kwargs):
            if args == ['hostname']: return 'spb-3-vm-t6fa'
            if args[:3] == ['docker', 'image', 'inspect']:
                return json.dumps([{'Id': context.BASELINE, 'RootFS': {'Layers': layers}}
                                   if args[3] == context.BASELINE else image])
            if args[:2] == ['docker', 'exec']: return json.dumps([{'site': site, 'key_exists': True} for site in shared.SITES])
            if args[:2] == ['docker', 'run']: return json.dumps(files)
            raise AssertionError('unexpected command')
        module = SimpleNamespace(run=Mock(side_effect=run), healthy=Mock(return_value=True), BENCH='/bench', BACKEND='backend')
        return module, shared, layers, report, image

    def test_only_two_committed_backend_files_and_all_134_tests_are_packaged(self):
        with directory() as root:
            path, report = self.package(root)
            self.assertEqual(set(report['files']), {'lms/lms/avo_import.py', 'lms/lms/test_avo_image_limits.py'})
            self.assertEqual(release.validate_context(path, REVISION), report)
            self.assertEqual(report['baseline_layers'], 49)
            self.assertEqual(len(context.BASELINE), 71)
            with tarfile.open(path.parent / 'overlay.tar') as archive:
                self.assertEqual(archive.getnames(), list(context.FILES))
                self.assertTrue(all(member.isfile() and member.mtime == 0 for member in archive.getmembers()))
            recipe = (path.parent / 'Dockerfile').read_text()
            previous = load('create_self_linked_image_context')
            self.assertEqual(context.TESTS, ('test_avo_image_limits',) + previous.TESTS)
            self.assertIn('RUN timeout 300s sh -c ', recipe)
            self.assertEqual(context.BUILD_MEMORY, '512m')
            self.assertTrue(all('lms.lms.' + name in recipe for name in context.TESTS))
            self.assertFalse(any(value in recipe for value in ('pip install', 'npm', 'yarn', 'migrate', 'frontend')))

    def test_uncommitted_generator_or_tampered_context_cannot_activate(self):
        with directory() as root:
            repo = root / 'repo'; repo.mkdir()
            with patch.object(context, 'git_bytes', side_effect=lambda *args: REVISION.encode() if args[1] == 'rev-parse' else b'dirty'):
                with self.assertRaisesRegex(ValueError, 'generator_not_committed'): context.create(root / 'context', repo)
            self.assertFalse((root / 'context').exists())
        with directory() as root:
            path, _ = self.package(root)
            (path.parent / 'overlay.tar').write_bytes(b'Unapproved content')
            with self.assertRaisesRegex(RuntimeError, 'artifact_changed'): release.validate_context(path, REVISION)

    def test_previous_profiles_and_general_guards_stay_unchanged(self):
        old = load('create_self_linked_image_context'); base = load('release_backend')
        self.assertEqual(old.BASELINE_LAYERS, 48)
        self.assertEqual(base.BASELINE_LAYERS, 47)
        self.assertEqual(context.BASELINE_LAYERS, 49); self.assertEqual(context.MAX_CANDIDATE_LAYERS, 50)
        self.assertNotEqual(old.BASELINE, context.BASELINE)
        self.assertIsNot(release.verify_candidate, base.verify_candidate)

    def test_valid_candidate_uses_existing_backups_cache_only_health_and_rollback(self):
        module, shared, _, report, _ = self.fake()
        with patch.object(release, 'deploy_helper', return_value=module), \
                patch.object(release, 'validate_context', return_value=report), \
                patch.object(release.os, 'geteuid', return_value=0, create=True):
            self.assertEqual(release.prepare(shared), 0)
            self.assertEqual(release.activate(CANDIDATE, '/backup', REVISION, '/manifest', shared), 0)
        shared.prepare.assert_called_once_with(); shared.validate_backup.assert_called_once_with('/backup')
        shared.activate.assert_called_once_with(CANDIDATE, '/backup', REVISION)
        calls = [call for call in module.run.call_args_list if call.args[0][:2] == ['docker', 'run']]
        self.assertEqual(len(calls), 1)
        command = calls[0].args[0]
        self.assertIn('--read-only', command); self.assertIn('--network=none', command)
        self.assertIn('--memory=256m', command); self.assertLessEqual(calls[0].kwargs['timeout'], 300)
        self.assertFalse(any('type=bind' in value or 'type=volume' in value for value in command))

    def test_51_layers_unknown_ancestry_or_bad_provenance_stops_before_activation(self):
        for failure in ('51_layers', 'unknown_layers', 'parent', 'label', 'checksum', 'baseline', 'unhealthy'):
            module, shared, layers, report, image = self.fake()
            if failure == '51_layers': image['RootFS']['Layers'].append('one-too-many')
            if failure == 'unknown_layers': image['RootFS'].pop('Layers')
            if failure == 'parent': image['RootFS']['Layers'][0] = 'foreign'
            if failure == 'label': image['Config']['Labels']['ru.mvcentr.release'] = 'foreign'
            if failure == 'baseline': layers.pop()
            if failure == 'unhealthy': module.healthy.return_value = False
            if failure == 'checksum':
                original = module.run.side_effect
                module.run.side_effect = lambda args, **kw: '{}' if args[:2] == ['docker', 'run'] else original(args, **kw)
            with self.subTest(failure=failure), patch.object(release, 'deploy_helper', return_value=module), \
                    patch.object(release, 'validate_context', return_value=report), \
                    patch.object(release.os, 'geteuid', return_value=0, create=True):
                with self.assertRaises(RuntimeError): release.activate(CANDIDATE, '/backup', REVISION, '/manifest', shared)
            shared.activate.assert_not_called()

    def test_rejected_backup_stops_before_any_candidate_probe_or_activation(self):
        module, shared, _, report, _ = self.fake(); shared.validate_backup.side_effect = RuntimeError('backup_not_fresh')
        with patch.object(release, 'deploy_helper', return_value=module), \
                patch.object(release, 'validate_context', return_value=report), \
                patch.object(release.os, 'geteuid', return_value=0, create=True):
            with self.assertRaisesRegex(RuntimeError, 'backup_not_fresh'):
                release.activate(CANDIDATE, '/backup', REVISION, '/manifest', shared)
        self.assertFalse(any(call.args[0][:2] == ['docker', 'run'] for call in module.run.call_args_list))
        shared.activate.assert_not_called()


if __name__ == '__main__': unittest.main()

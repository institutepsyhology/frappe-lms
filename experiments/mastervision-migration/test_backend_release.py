"""Synthetic packaging/release guards; no Docker, SSH, accounts or real data."""
import contextlib
import importlib.util
import io
import json
from pathlib import Path
import shutil
import tarfile
import tempfile
from types import SimpleNamespace
import unittest
import uuid
from unittest.mock import Mock, patch

HERE = Path(__file__).resolve().parent


def load(name):
    spec = importlib.util.spec_from_file_location('backend_test_' + name, HERE / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


context, release = load('create_backend_context'), load('release_backend')
REVISION, CANDIDATE = '1' * 40, 'sha256:' + '2' * 64


@contextlib.contextmanager
def directory():
    parent = Path(tempfile.gettempdir()).resolve(strict=True)
    root = parent / ('backend-release-fixture-' + uuid.uuid4().hex)
    root.mkdir()
    try:
        yield root
    finally:
        if root.parent.resolve(strict=True) != parent or not root.name.startswith('backend-release-fixture-'):
            raise RuntimeError('unsafe_fixture_cleanup')
        shutil.rmtree(root)


def git(repo, *args):
    if args[0] == 'rev-parse':
        return REVISION.encode()
    name = args[1].split(':', 1)[1]
    return ((HERE / 'create_backend_context.py').read_bytes().replace(b'\r\n', b'\n')
            if name == context.GENERATOR else ('committed ' + name + '\n').encode())


def package(root):
    repo = root / 'repo'; repo.mkdir(exist_ok=True)
    with patch.object(context, 'git_bytes', side_effect=git):
        report = context.create(root / 'context', repo)
    return root / 'context/source-manifest.json', report


class ContextTests(unittest.TestCase):
    def test_deterministic_only_committed_transform_tests_and_fixture(self):
        with directory() as root:
            path, report = package(root)
            repo = root / 'repo'
            with patch.object(context, 'git_bytes', side_effect=git) as calls:
                second = context.create(root / 'second', repo)
            self.assertEqual(report, second)
            with tarfile.open(path.parent / 'overlay.tar') as archive:
                self.assertEqual(archive.getnames(), list(context.FILES))
                for item in archive.getmembers():
                    self.assertEqual(item.mtime, 0)
                    self.assertEqual(archive.extractfile(item).read(), ('committed ' + item.name + '\n').encode())
            self.assertEqual(release.validate_context(path, REVISION), report)
            recipe = (path.parent / 'Dockerfile').read_text()
            self.assertTrue(recipe.startswith('FROM ' + context.BASELINE + '\n'))
            self.assertIn(REVISION, recipe)
            self.assertIn('python -B -m unittest lms.lms.test_avo_inline_images', recipe)
            self.assertNotIn('\n+', recipe)
            self.assertFalse(any(value in recipe for value in ('yarn', 'npm', 'pip install', 'frontend')))
            self.assertTrue(all(call.args[1] in ('show', 'rev-parse') for call in calls.call_args_list))

    def test_uncommitted_generator_rejected_before_creation(self):
        with directory() as root:
            repo = root / 'repo'; repo.mkdir()
            def dirty(*args):
                return b'changed generator' if args[1] == 'show' else REVISION.encode()
            with patch.object(context, 'git_bytes', side_effect=dirty):
                with self.assertRaisesRegex(ValueError, 'generator_not_committed'):
                    context.create(root / 'context', repo)
            self.assertFalse((root / 'context').exists())

    def test_refuses_inside_checkout_or_existing_destination(self):
        with directory() as root:
            repo = root / 'repo'; repo.mkdir()
            with self.assertRaisesRegex(ValueError, 'outside_checkout'):
                context.create(repo / 'context', repo)
            with self.assertRaisesRegex(ValueError, 'destination_exists'):
                context.create(repo, repo)

    def test_context_checks_artifact_bytes_and_exact_member_allowlist(self):
        with directory() as root:
            path, report = package(root)
            (path.parent / 'Dockerfile').write_bytes(b'FROM foreign-image\n')
            with self.assertRaisesRegex(RuntimeError, 'artifact_changed'):
                release.validate_context(path, REVISION)
            (path.parent / 'Dockerfile').write_bytes(context.dockerfile(REVISION, report['files'], report['generator_sha256']))
            with tarfile.open(path.parent / 'overlay.tar', 'a') as archive:
                info = tarfile.TarInfo('frontend/foreign.js'); info.size = 1
                archive.addfile(info, io.BytesIO(b'x'))
            report['overlay_sha256'] = context.sha((path.parent / 'overlay.tar').read_bytes())
            path.write_text(json.dumps(report))
            with self.assertRaisesRegex(RuntimeError, 'overlay_source_allowlist'):
                release.validate_context(path, REVISION)

    def test_wrong_release_source_or_file_allowlist_rejected(self):
        with directory() as root:
            path, report = package(root)
            for key, value in [('source_revision', '3' * 40), ('baseline_image', 'foreign'),
                               ('release', 'other'), ('files', {'lms/hooks.py': 'a' * 64})]:
                changed = dict(report); changed[key] = value
                path.write_text(json.dumps(changed))
                with self.assertRaises(RuntimeError):
                    release.validate_context(path, REVISION)


class ReleaseTests(unittest.TestCase):
    def fake(self):
        layers = ['sha256:' + str(index).zfill(64) for index in range(47)]
        files = {name: 'a' * 64 for name in context.FILES}
        report = {'source_revision': REVISION, 'files': files, 'generator_sha256': 'b' * 64}
        labels = {'org.opencontainers.image.source': context.SOURCE,
                  'org.opencontainers.image.revision': REVISION,
                  'ru.mvcentr.release': context.RELEASE, 'ru.mvcentr.baseline': context.BASELINE,
                  'ru.mvcentr.sources-sha256': context.sources_digest(files),
                  'ru.mvcentr.generator-sha256': report['generator_sha256']}
        image = {'Id': CANDIDATE, 'RootFS': {'Layers': layers + ['new-layer']}, 'Config': {'Labels': labels}}
        def run(args, **kwargs):
            if args == ['hostname']: return 'spb-3-vm-t6fa'
            if args[:3] == ['docker', 'image', 'inspect']:
                return json.dumps([{'Id': context.BASELINE, 'RootFS': {'Layers': layers}}
                                   if args[3] == context.BASELINE else image])
            if args[:2] == ['docker', 'exec']:
                return json.dumps([{'site': site, 'key_exists': True} for site in shared.SITES])
            if args[:2] == ['docker', 'run']: return json.dumps(files)
            raise AssertionError('unexpected command')
        module = SimpleNamespace(run=Mock(side_effect=run), healthy=Mock(return_value=True), BENCH='/bench', BACKEND='backend')
        shared = SimpleNamespace(SITES=('one', 'two', 'three'), prepare=Mock(return_value=0),
                                 activate=Mock(return_value=0), validate_backup=Mock())
        return module, shared, layers, report, image

    def test_preparation_requires_existing_keys_before_backup_helper(self):
        module, shared, *_ = self.fake()
        with patch.object(release, 'deploy_helper', return_value=module), \
                patch.object(release.os, 'geteuid', return_value=0, create=True):
            self.assertEqual(release.prepare(shared), 0)
        shared.prepare.assert_called_once_with()
        code = next(call.args[0][-1] for call in module.run.call_args_list if call.args[0][:2] == ['docker', 'exec'])
        for forbidden in ('get_encryption_key', '.connect(', '.commit(', 'ensure_'):
            self.assertNotIn(forbidden, code)

    def test_missing_key_stops_before_backups_or_activation(self):
        module, shared, *_ = self.fake()
        original = module.run.side_effect
        module.run.side_effect = lambda args, **kw: '[]' if args[:2] == ['docker', 'exec'] else original(args, **kw)
        with patch.object(release, 'deploy_helper', return_value=module), \
                patch.object(release.os, 'geteuid', return_value=0, create=True):
            with self.assertRaisesRegex(RuntimeError, 'existing_encryption_key_required'):
                release.prepare(shared)
        shared.prepare.assert_not_called(); shared.activate.assert_not_called()

    def test_valid_candidate_delegates_to_cache_only_shared_release(self):
        module, shared, layers, report, _ = self.fake()
        with patch.object(release, 'deploy_helper', return_value=module), \
                patch.object(release, 'validate_context', return_value=report), \
                patch.object(release.os, 'geteuid', return_value=0, create=True):
            self.assertEqual(release.activate(CANDIDATE, '/backup', REVISION, '/context', shared), 0)
        shared.validate_backup.assert_called_once_with('/backup')
        shared.activate.assert_called_once_with(CANDIDATE, '/backup', REVISION)
        probe = next(call.args[0] for call in module.run.call_args_list if call.args[0][:2] == ['docker', 'run'])
        self.assertIn('--network=none', probe); self.assertIn('--read-only', probe)
        self.assertFalse(any('type=bind' in value or 'type=volume' in value for value in probe))

    def test_bad_ancestry_provenance_or_candidate_bytes_stop_activation(self):
        for failure in ('prefix', 'too_many_layers', 'label', 'checksum'):
            module, shared, layers, report, image = self.fake()
            if failure == 'prefix': image['RootFS']['Layers'][0] = 'foreign-layer'
            if failure == 'too_many_layers': image['RootFS']['Layers'] += ['extra-one', 'extra-two']
            if failure == 'label': image['Config']['Labels']['org.opencontainers.image.revision'] = '9' * 40
            if failure == 'checksum':
                original = module.run.side_effect
                module.run.side_effect = lambda args, **kw: '{}' if args[:2] == ['docker', 'run'] else original(args, **kw)
            with patch.object(release, 'deploy_helper', return_value=module), \
                    patch.object(release, 'validate_context', return_value=report), \
                    patch.object(release.os, 'geteuid', return_value=0, create=True):
                with self.assertRaises(RuntimeError):
                    release.activate(CANDIDATE, '/backup', REVISION, '/context', shared)
            shared.activate.assert_not_called()

    def test_changed_runtime_or_non_47_baseline_stops(self):
        for failure in ('runtime', 'layers'):
            module, shared, layers, *_ = self.fake()
            if failure == 'runtime': module.healthy.return_value = False
            else: layers.pop()
            with patch.object(release, 'deploy_helper', return_value=module), \
                    patch.object(release.os, 'geteuid', return_value=0, create=True):
                with self.assertRaises(RuntimeError): release.prepare(shared)
            shared.prepare.assert_not_called()

    def test_wrong_host_or_rejected_backup_never_runs_candidate_or_activation(self):
        for failure in ('host', 'backup'):
            module, shared, _, report, _ = self.fake()
            if failure == 'host':
                original = module.run.side_effect
                module.run.side_effect = lambda args, **kw: 'other-host' if args == ['hostname'] else original(args, **kw)
            else:
                shared.validate_backup.side_effect = RuntimeError('backup_not_fresh')
            with patch.object(release, 'deploy_helper', return_value=module), \
                    patch.object(release, 'validate_context', return_value=report), \
                    patch.object(release.os, 'geteuid', return_value=0, create=True):
                with self.assertRaises(RuntimeError):
                    release.activate(CANDIDATE, '/backup', REVISION, '/context', shared)
            shared.activate.assert_not_called()
            self.assertFalse(any(call.args[0][:2] == ['docker', 'run'] for call in module.run.call_args_list))

    def test_new_wrapper_only_changes_imported_helper_constants(self):
        shared = release.shared_release()
        self.assertEqual((shared.BASELINE, shared.RELEASE), (context.BASELINE, context.RELEASE))
        self.assertEqual(shared.HERE.name, 'private-course-access')


if __name__ == '__main__':
    unittest.main()

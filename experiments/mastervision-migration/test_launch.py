"""Synthetic Git/cache/job tests. No browser, network, or background job is run."""
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import tarfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock
import uuid

import launch as mod


def archive(extra=None):
    stream = io.BytesIO()
    with tarfile.open(fileobj=stream, mode='w') as output:
        for name in sorted(mod.REQUIRED):
            data = b'# committed public source\n'
            item = tarfile.TarInfo(name); item.size = len(data)
            output.addfile(item, io.BytesIO(data))
        if extra:
            item, data = extra
            output.addfile(item, io.BytesIO(data) if data is not None else None)
    return stream.getvalue()


class ArgumentArchiveTests(unittest.TestCase):
    def test_multiple_explicit_courses_are_canonical_and_bounded(self):
        arguments = ['--stored', '--apply'] + [part for cid in range(1, 29) for part in ('--course', str(cid))]
        self.assertEqual(mod.validate_flags(arguments), arguments)
        with self.assertRaises(mod.LaunchError):
            mod.validate_flags(['--course', '2', '--course', '2'])
        with self.assertRaises(mod.LaunchError):
            mod.validate_flags(['--apply'] * 257)

    def test_whitelisted_flags_preserve_values_and_order(self):
        args = ['--apply', '--stored', '--from-course', '7', '--limit', '10', '--resume']
        self.assertEqual(mod.parse_arguments(['--revision', 'a' * 40, *args]), {'revision': 'a' * 40, 'arguments': args})
        self.assertEqual(mod.parse_arguments(['--settings-only', '--course', '618']),
                         {'revision': 'HEAD', 'arguments': ['--settings-only', '--course', '618']})

    def test_unknown_duplicate_flags_and_noncanonical_ids_never_reach_git(self):
        for args in (['--cookie', 'PRIVATE'], ['--apply', '--apply'], ['--course', '0'],
                     ['--course', '01'], ['--limit', '-1'], ['--from-course', '2147483648'],
                     ['--limit'], ['--monitor', 'x', '--apply']):
            with self.subTest(args=args), self.assertRaises(mod.LaunchError): mod.parse_arguments(args)
        for revision in ('--help', '../private', 'HEAD;echo', 'HEAD^{tree}'):
            with self.subTest(revision=revision), self.assertRaises(mod.LaunchError):
                mod.parse_arguments(['--revision', revision])

    def test_archive_accepts_only_approved_public_sources(self):
        self.assertEqual(set(mod.archive_sources(archive())), mod.REQUIRED)

    def test_traversal_links_and_unexpected_payloads_are_rejected(self):
        for name in ('../credentials.py', '/absolute.py', 'C:/private.py',
                     'experiments/mastervision-migration/../../private.py',
                     'experiments\\mastervision-migration\\secret.py',
                     'experiments/mastervision-migration/private.json', 'frappe-mcp/headers.py'):
            item = tarfile.TarInfo(name); item.size = 1
            with self.subTest(name=name), self.assertRaises(mod.LaunchError):
                mod.archive_sources(archive((item, b'x')))
        for kind in (tarfile.SYMTYPE, tarfile.LNKTYPE):
            item = tarfile.TarInfo(mod.PREFIX + 'linked.py'); item.type = kind; item.linkname = '../../private'
            with self.subTest(kind=kind), self.assertRaisesRegex(mod.LaunchError, 'archive_links_forbidden'):
                mod.archive_sources(archive((item, None)))

    def test_oversized_code_and_duplicate_entries_are_rejected(self):
        item = tarfile.TarInfo(mod.PREFIX + 'large.py'); item.size = mod.MAX_SOURCE_BYTES + 1
        with self.assertRaisesRegex(mod.LaunchError, 'archive_size_invalid'):
            mod.archive_sources(archive((item, b'x' * item.size)))
        item = tarfile.TarInfo(mod.ENTRY); item.size = 1
        with self.assertRaisesRegex(mod.LaunchError, 'duplicate_archive_path'):
            mod.archive_sources(archive((item, b'x')))


class GitJobTests(unittest.TestCase):
    def setUp(self):
        self.parent = Path(__file__).resolve().parents[3] / '.mv-launch-tests'
        self.parent.mkdir(exist_ok=True)
        self.folder = self.parent / ('fixture-' + uuid.uuid4().hex[:8]); self.folder.mkdir()
        self.addCleanup(self.cleanup)
        self.repo, self.workspace = self.folder / 'repo', self.folder / 'w'
        self.repo.mkdir(); self.workspace.mkdir()
        helper = self.workspace / 'frappe-mcp/headers.py'; helper.parent.mkdir()
        helper.write_text('# synthetic workspace marker, no credentials\n')
        self.git('init', '--quiet')
        for relative in mod.REQUIRED:
            path = self.repo / relative; path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('# COMMITTED PUBLIC SOURCE\n', encoding='utf-8')
        self.git('add', '.')
        self.git('-c', 'user.name=Synthetic Test', '-c', 'user.email=test@example.invalid', 'commit', '--quiet', '-m', 'synthetic source')

    def git(self, *args):
        return subprocess.run(['git', '-C', str(self.repo), '-c', 'core.hooksPath=' + str(self.folder / 'no-hooks'),
            '-c', 'commit.gpgsign=false', *args], check=True, capture_output=True,
            env={**os.environ, 'GIT_CONFIG_NOSYSTEM': '1'},
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0)).stdout

    def cleanup(self):
        if self.folder.resolve().parent != self.parent.resolve() or not self.folder.name.startswith('fixture-'):
            raise RuntimeError('unsafe_fixture_cleanup')
        def writable_retry(function, path, error):
            resolved = Path(path).resolve()
            if not resolved.is_relative_to(self.folder.resolve()): raise RuntimeError('unsafe_fixture_cleanup')
            os.chmod(path, stat.S_IWRITE | stat.S_IREAD)
            function(path)
        shutil.rmtree(self.folder, onexc=writable_retry)

    def start(self, arguments=None):
        factory = Mock(return_value=SimpleNamespace(pid=24680))
        result = mod.launch(self.repo, self.workspace, arguments or ['--apply', '--from-course', '7'], process_factory=factory)
        job_file = Path(result['job_file'])
        job = json.loads(job_file.read_bytes())
        cache = self.workspace / 'exports/lesson-content/mastervision-migration/code' / job['source_commit']
        return result, job_file, job, cache, factory

    def test_uncommitted_working_changes_and_private_untracked_files_are_never_exported(self):
        (self.repo / mod.ENTRY).write_text('UNCOMMITTED PRIVATE SOURCE\n')
        (self.repo / mod.PREFIX / 'private.json').write_text('UNTRACKED PRIVATE SOURCE\n')
        cache, commit, digest = mod.prepare_code(self.repo, self.workspace)
        self.assertEqual((cache / mod.ENTRY).read_text(), '# COMMITTED PUBLIC SOURCE\n')
        self.assertFalse((cache / mod.PREFIX / 'private.json').exists())
        self.assertEqual(commit, self.git('rev-parse', 'HEAD').decode().strip())
        self.assertEqual(digest, hashlib.sha256((cache / mod.MANIFEST).read_bytes()).hexdigest())
        self.assertEqual(mod.prepare_code(self.repo, self.workspace)[0], cache)

    def test_tampered_cache_is_rejected_instead_of_silently_replaced(self):
        cache, _, _ = mod.prepare_code(self.repo, self.workspace)
        (cache / mod.ENTRY).write_text('TAMPERED\n')
        with self.assertRaisesRegex(mod.LaunchError, 'cache_integrity_invalid'):
            mod.prepare_code(self.repo, self.workspace)

    def test_starter_runs_only_the_committed_monitor_with_private_job_metadata(self):
        result, job_file, job, cache, factory = self.start()
        args, kwargs = factory.call_args
        self.assertEqual(args[0], [mod.sys.executable, '-B', str(cache / mod.MONITOR), '--monitor', str(job_file)])
        self.assertEqual(kwargs['env']['MASTER_VISION_WORKSPACE'], str(self.workspace.resolve()))
        self.assertEqual(kwargs['env']['PYTHONDONTWRITEBYTECODE'], '1')
        self.assertEqual(kwargs['cwd'], str(cache))
        self.assertEqual(job['status'], 'starting')
        self.assertEqual(result['monitor_pid'], 24680)
        self.assertEqual(job_file.with_suffix('.log').read_bytes(), b'')
        self.assertNotIn('PRIVATE', json.dumps(job))

    def test_monitor_records_final_exit_from_cached_run_and_private_log(self):
        for exit_code in (0, 3):
            with self.subTest(exit_code=exit_code):
                _, path, job, cache, _ = self.start()
                process = SimpleNamespace(pid=13579, wait=Mock(return_value=exit_code), poll=Mock(return_value=exit_code))
                def child(command, **kwargs):
                    self.assertEqual(command, [mod.sys.executable, '-B', str(cache / mod.ENTRY), *job['arguments']])
                    self.assertEqual(kwargs['env']['MASTER_VISION_WORKSPACE'], str(self.workspace))
                    kwargs['stdout'].write(b'{"status":"synthetic_finished"}\n')
                    return process
                self.assertEqual(mod.monitor(path, workspace=self.workspace, process_factory=child, current_script=cache / mod.MONITOR), exit_code)
                final = json.loads(path.read_bytes())
                self.assertEqual(final['status'], 'completed' if exit_code == 0 else 'failed')
                self.assertEqual(final['pid'], 13579)
                self.assertEqual(final['source_commit'], job['source_commit'])
                self.assertEqual(final['exit_code'], exit_code)
                self.assertTrue(final['started_at_utc'] and final['finished_at_utc'])
                self.assertEqual(path.with_suffix('.log').read_bytes(), b'{"status":"synthetic_finished"}\n')

    def test_monitor_rejects_tampered_flags_before_spawning_anything(self):
        _, path, job, cache, _ = self.start(); job['arguments'].append('--private-cookie')
        path.write_bytes(mod._json(job)); factory = Mock()
        with self.assertRaisesRegex(mod.LaunchError, 'invalid_run_argument'):
            mod.monitor(path, workspace=self.workspace, process_factory=factory, current_script=cache / mod.MONITOR)
        factory.assert_not_called()

    def test_bad_provenance_is_persisted_as_failure_without_worker_start(self):
        _, path, _, cache, _ = self.start(); (cache / mod.ENTRY).write_text('TAMPERED\n')
        factory = Mock()
        self.assertEqual(mod.monitor(path, workspace=self.workspace, process_factory=factory, current_script=cache / mod.MONITOR), 1)
        factory.assert_not_called()
        state = json.loads(path.read_bytes())
        self.assertEqual((state['status'], state['error']), ('failed', 'cache_integrity_invalid'))

    def test_working_tree_monitor_cannot_run_a_cached_job(self):
        _, path, _, _, _ = self.start(); factory = Mock()
        self.assertEqual(mod.monitor(path, workspace=self.workspace, process_factory=factory, current_script=self.repo / mod.MONITOR), 1)
        factory.assert_not_called()
        self.assertEqual(json.loads(path.read_bytes())['error'], 'monitor_source_mismatch')

    def test_monitor_spawn_failure_is_fixed_metadata_without_exception_contents(self):
        _, path, _, cache, _ = self.start()
        factory = Mock(side_effect=OSError('PRIVATE ENVIRONMENT TOKEN'))
        self.assertEqual(mod.monitor(path, workspace=self.workspace, process_factory=factory, current_script=cache / mod.MONITOR), 1)
        state = json.loads(path.read_bytes())
        self.assertEqual(state['error'], 'worker_start_or_monitor_failed')
        self.assertNotIn('PRIVATE', json.dumps(state))

    def test_job_outside_own_jobs_directory_is_rejected(self):
        _, path, _, cache, _ = self.start(); foreign = self.workspace / path.name
        foreign.write_bytes(path.read_bytes()); factory = Mock()
        with self.assertRaisesRegex(mod.LaunchError, 'invalid_job_file'):
            mod.monitor(foreign, workspace=self.workspace, process_factory=factory, current_script=cache / mod.MONITOR)
        factory.assert_not_called()


if __name__ == '__main__': unittest.main()

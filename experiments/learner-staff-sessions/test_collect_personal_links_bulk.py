"""Offline synthetic-only tests; never contact AVO, Frappe, or redeem login URLs."""
from contextlib import closing, contextmanager, redirect_stderr, redirect_stdout
from datetime import datetime, timezone
import io
import json
import os
from pathlib import Path
import sqlite3
import unittest
from unittest.mock import patch
import uuid

from audit_legacy_links import SHOP_HOST, inspect_record
import collect_personal_links_bulk as bulk
from collect_personal_links import CollectionError
from private_link_storage import StorageError, protect_url, unprotect_url
from test_audit_legacy_links import row, synthetic_database


KEY = 'SYNTHETIC_API_SECRET_NEVER_PRINT'


def detail(ident, token=None):
    return {'id_contact': str(ident), 'password': 'SYNTHETIC_PASSWORD_DISCARD',
            'email': 'SYNTHETIC_PRIVATE_EMAIL@example.invalid',
            'link_personal_auth': f'https://{SHOP_HOST}/personal/auth/secure-login?uid={ident}'
                                 f'&vc={token or "SYNTHETIC_TOKEN_" + str(ident)}'}


def source_archive(path, count=3):
    with closing(sqlite3.connect(path)) as db:
        db.execute('CREATE TABLE contacts (id INTEGER PRIMARY KEY, record_json TEXT)')
        db.executemany('INSERT INTO contacts VALUES (?, ?)',
                       [(ident, json.dumps(row(ident))) for ident in range(1, count + 1)])
        db.commit()


@contextmanager
def output_directory():
    # Existing workspace directory outside the repository avoids Windows TEMP ACLs.
    root = Path(__file__).resolve().parents[3] / 'exports'
    root.mkdir(exist_ok=True)
    directory = root / ('.synthetic-bulk-' + uuid.uuid4().hex)
    directory.mkdir()
    try:
        yield directory
    finally:
        # Fixed synthetic files only, no recursive filesystem operation.
        for name in ('links.sqlite', 'links.sqlite-wal', 'links.sqlite-shm', 'links.sqlite-journal',
                     'collector.lock', 'progress.json', 'progress.json.tmp', 'STOP'):
            (directory / name).unlink(missing_ok=True)
        directory.rmdir()


class Clock:
    def __init__(self):
        self.now = 0.0
        self.waits = []

    def __call__(self):
        return self.now

    def wait(self, duration):
        self.waits.append(duration)
        self.now += duration


def run(source, output, fetch=None, **options):
    clock = options.pop('clock', Clock())
    return bulk.collect(source, output, account='mv-centr', key=KEY,
                        fetch=fetch or (lambda key, ident: detail(ident)),
                        clock=clock, wait=clock.wait, **options)


def count(directory, table):
    with closing(sqlite3.connect(directory / 'links.sqlite')) as db:
        return db.execute('SELECT COUNT(*) FROM ' + table).fetchone()[0]


class BulkCollectionTests(unittest.TestCase):
    def test_control_error_logs_category_without_exception_contents(self):
        with synthetic_database() as source, output_directory() as output:
            source_archive(source, 1)
            original = bulk.atomic_progress
            calls = []

            def fail_once(directory, report):
                calls.append(report['status'])
                if len(calls) == 3:
                    error = PermissionError(13, 'SYNTHETIC_PRIVATE_EXCEPTION_' + KEY)
                    error.winerror = 5
                    raise error
                return original(directory, report)

            with patch.object(bulk, 'atomic_progress', side_effect=fail_once):
                report = run(source, output)
            self.assertEqual(report['status'], 'stopped_fatal_error')
            self.assertEqual(report['verified_total'], 1)
            with closing(sqlite3.connect(output / 'links.sqlite')) as db:
                diagnostics = db.execute('SELECT stage,error_type,errno,winerror FROM diagnostics').fetchall()
            self.assertIn(('write_progress', 'PermissionError', 13, 5), diagnostics)
            self.assertNotIn(KEY, (output / 'links.sqlite').read_bytes().decode('latin1'))
            self.assertNotIn(KEY, (output / 'progress.json').read_text())
            resumed = run(source, output)
            self.assertEqual(resumed['verified_total'], 1)
            self.assertEqual(resumed['skipped'], 1)

    def test_all_individual_cards_encrypted_and_source_unchanged(self):
        with synthetic_database() as source, output_directory() as output:
            source_archive(source, 4)
            original = source.read_bytes()
            calls = []
            clock = Clock()

            def fetch(key, ident):
                self.assertEqual(key, KEY)
                calls.append((ident, clock()))
                return {'data': [detail(ident)]}

            report = run(source, output, fetch, clock=clock)
            self.assertEqual(report['status'], 'completed')
            self.assertEqual(report['verified_total'], 4)
            self.assertEqual([ident for ident, _ in calls], [1, 2, 3, 4])
            self.assertTrue(all(calls[i][1] - calls[i-1][1] >= 1 for i in range(1, len(calls))))
            self.assertEqual(source.read_bytes(), original)
            with closing(sqlite3.connect(output / 'links.sqlite')) as db:
                for ident, encrypted, origin in db.execute('SELECT source_id,url_encrypted,capture_origin FROM links'):
                    self.assertEqual(unprotect_url(ident, encrypted), detail(ident)['link_personal_auth'])
                    self.assertEqual(origin, 'individual_detail')
                self.assertEqual(db.execute('PRAGMA journal_mode').fetchone()[0], 'wal')
            private_bytes = b''.join(path.read_bytes() for path in output.iterdir() if path.is_file())
            for secret in (KEY, 'SYNTHETIC_TOKEN_', 'SYNTHETIC_PASSWORD_DISCARD', 'SYNTHETIC_PRIVATE_EMAIL'):
                self.assertNotIn(secret.encode(), private_bytes)
                self.assertNotIn(secret, json.dumps(report))
            progress = json.loads((output / 'progress.json').read_text())
            self.assertEqual(progress['verified_total'], 4)
            self.assertNotIn('source_id', progress)

    def test_failure_never_success_and_resume_retries_only_missing(self):
        with synthetic_database() as source, output_directory() as output:
            source_archive(source)

            def fetch(key, ident):
                if ident == 2:
                    raise CollectionError('http_404')
                return detail(ident)

            first = run(source, output, fetch)
            self.assertEqual(first['status'], 'completed_with_failures')
            self.assertEqual(first['verified_total'], 2)
            self.assertEqual(count(output, 'contact_state'), 2)
            calls = []
            second = run(source, output, lambda key, ident: calls.append(ident) or detail(ident))
            self.assertEqual(calls, [2])
            self.assertEqual(second['skipped'], 2)
            self.assertEqual(second['verified_total'], 3)
            self.assertEqual(count(output, 'links'), 3)
            # A fully complete resume needs no API key prompt at all.
            done = bulk.collect(source, output, account='mv-centr',
                key_provider=lambda *_: self.fail('prompt'), fetch=lambda *_: self.fail('network'))
            self.assertEqual(done['skipped'], 3)

    def test_refresh_appends_changed_and_unchanged_versions(self):
        with synthetic_database() as source, output_directory() as output:
            source_archive(source, 1)
            run(source, output)
            run(source, output, lambda key, ident: detail(ident, 'SYNTHETIC_CHANGED_VC'), refresh=True)
            run(source, output, lambda key, ident: detail(ident, 'SYNTHETIC_CHANGED_VC'), refresh=True)
            self.assertEqual(count(output, 'links'), 3)
            self.assertEqual(count(output, 'contact_state'), 1)
            with closing(sqlite3.connect(output / 'links.sqlite')) as db:
                urls = [unprotect_url(ident, encrypted) for ident, encrypted in db.execute(
                    'SELECT source_id,url_encrypted FROM links ORDER BY version_id')]
            self.assertEqual(urls[0], detail(1)['link_personal_auth'])
            self.assertEqual(urls[1:], [detail(1, 'SYNTHETIC_CHANGED_VC')['link_personal_auth']] * 2)

    def test_seed_decrypts_and_revalidates_preflight(self):
        with synthetic_database() as source, synthetic_database() as seed, output_directory() as output:
            source_archive(source, 4)
            with closing(sqlite3.connect(seed)) as db:
                db.execute('CREATE TABLE links (source_id,url_encrypted,token_digest,captured_at,source_field)')
                for ident in (1, 2, 3):
                    url = detail(ident)['link_personal_auth']
                    digest = inspect_record(ident, row(ident, url))[1]
                    db.execute('INSERT INTO links VALUES (?,?,?,?,?)',
                        (ident, protect_url(ident, url), digest, datetime.now(timezone.utc).isoformat(),
                         'link_personal_auth'))
                db.commit()
            before = seed.read_bytes()
            calls = []
            report = run(source, output, lambda key, ident: calls.append(ident) or detail(ident), seed_database=seed)
            self.assertEqual(report['seeded'], 3)
            self.assertEqual(calls, [4])
            self.assertEqual(report['verified_total'], 4)
            self.assertEqual(seed.read_bytes(), before)

    def test_seed_wrong_uid_does_not_get_marked_success(self):
        with synthetic_database() as source, synthetic_database() as seed, output_directory() as output:
            source_archive(source)
            url = detail(2)['link_personal_auth']
            with closing(sqlite3.connect(seed)) as db:
                db.execute('CREATE TABLE links (source_id,url_encrypted,token_digest,captured_at,source_field)')
                db.execute('INSERT INTO links VALUES (?,?,?,?,?)',
                    (1, protect_url(1, url), b'not-a-real-digest', datetime.now(timezone.utc).isoformat(),
                     'link_personal_auth'))
                db.commit()
            report = run(source, output, lambda *_: self.fail('network'), seed_database=seed)
            self.assertEqual(report['error_code'], 'detail_url_uid_mismatch')
            self.assertEqual(count(output, 'contact_state'), 0)

    def test_full_source_validation_precedes_key_or_network(self):
        for mutation in ('foreign_account', 'id_mismatch', 'zero', 'not_json'):
            with self.subTest(case=mutation), synthetic_database() as source, output_directory() as output:
                source_archive(source)
                record = row(3)
                if mutation == 'foreign_account':
                    record['source'] = 'https://mastervision.autoweboffice.ru'
                elif mutation == 'id_mismatch':
                    record['contact']['id'] = 99
                with closing(sqlite3.connect(source)) as db:
                    db.execute('UPDATE contacts SET id=?,record_json=? WHERE id=3',
                        (0 if mutation == 'zero' else 3, 'not-json' if mutation == 'not_json' else json.dumps(record)))
                    db.commit()
                with self.assertRaises(bulk.BulkError):
                    bulk.collect(source, output, account='mv-centr',
                        key_provider=lambda *_: self.fail('prompt'), fetch=lambda *_: self.fail('network'))
                self.assertFalse((output / 'links.sqlite').exists())

    def test_explicit_wrong_account_rejected(self):
        with synthetic_database() as source, output_directory() as output:
            source_archive(source)
            with self.assertRaisesRegex(bulk.BulkError, '^wrong_account$'):
                bulk.collect(source, output, account='mastervision', key=KEY,
                             fetch=lambda *_: self.fail('network'))

    def test_output_in_repository_and_source_overlap_refused(self):
        with synthetic_database() as source:
            source_archive(source)
            with self.assertRaisesRegex(bulk.BulkError, '^private_output_required$'):
                run(source, Path(__file__).resolve().parent)
        with output_directory() as output:
            source = output / 'links.sqlite'
            source_archive(source)
            with self.assertRaisesRegex(bulk.BulkError, '^source_output_overlap$'):
                run(source, output)

    def test_key_leaks_and_foreign_links_stop_immediately(self):
        encoded = KEY
        for _ in range(4):
            encoded = ''.join('%%%02X' % ord(character) for character in encoded)
        for token, host in ((KEY, SHOP_HOST), (encoded, SHOP_HOST), ('safe', 'shop.mastervision.su')):
            with self.subTest(host=host, encoded=token != KEY), synthetic_database() as source, output_directory() as output:
                source_archive(source)
                calls = []

                def fetch(key, ident):
                    calls.append(ident)
                    result = detail(ident, token)
                    result['link_personal_auth'] = result['link_personal_auth'].replace(SHOP_HOST, host)
                    return result

                report = run(source, output, fetch)
                self.assertEqual(calls, [1])
                self.assertEqual(report['status'], 'stopped_fatal_error')
                self.assertEqual(count(output, 'links'), 0)
                self.assertNotIn(KEY, json.dumps(report))

    def test_too_deep_encoding_fails_closed(self):
        encoded = '%41'
        for _ in range(20):
            encoded = encoded.replace('%', '%25')
        with self.assertRaisesRegex(bulk.BulkError, '^link_encoding_too_deep$'):
            bulk.reject_key_leak('https://example.invalid/?vc=' + encoded, KEY)

    def test_ten_failures_stop_but_intervening_success_resets(self):
        with synthetic_database() as source, output_directory() as output:
            source_archive(source, 30)
            calls = []

            def fetch(key, ident):
                calls.append(ident)
                if ident == 10:
                    return detail(ident)
                raise CollectionError('http_404')

            report = run(source, output, fetch)
            self.assertEqual(calls, list(range(1, 21)))
            self.assertEqual(report['status'], 'stopped_consecutive_failures')
            self.assertEqual(report['failed_contacts'], 19)
            self.assertEqual(report['consecutive_failures'], 10)
            self.assertEqual(report['verified_total'], 1)

    def test_auth_and_structural_errors_stop_first_without_retry(self):
        for code in ('http_401', 'http_403', 'wrong_contact', 'unexpected_detail_structure',
                     'detail_url_uid_mismatch', 'detail_invalid_link_type_or_length'):
            with self.subTest(code=code), synthetic_database() as source, output_directory() as output:
                source_archive(source)
                calls = []

                def fetch(key, ident):
                    calls.append(ident)
                    raise CollectionError(code)

                report = run(source, output, fetch)
                self.assertEqual(report['error_code'], code)
                self.assertEqual(calls, [1])
                self.assertEqual(report['verified_total'], 0)

    def test_bounded_retries_retry_after_and_permanent_errors(self):
        with synthetic_database() as source, output_directory() as output:
            source_archive(source, 2)
            clock = Clock()
            calls = []

            def fetch(key, ident):
                calls.append((ident, clock()))
                if len(calls) == 1:
                    error = CollectionError('http_429')
                    # Same chain available after the read-only helper suppresses HTTPError text.
                    error.__context__ = Exception('SYNTHETIC_DO_NOT_PRINT')
                    error.__context__.headers = {'Retry-After': '7'}
                    raise error
                if ident == 2:
                    raise CollectionError('http_404')
                return detail(ident)

            report = run(source, output, fetch, clock=clock)
            self.assertEqual([ident for ident, _ in calls], [1, 1, 2])
            self.assertGreaterEqual(calls[1][1] - calls[0][1], 7)
            self.assertEqual(report['request_attempts'], 3)
            self.assertEqual(report['verified_total'], 1)
            self.assertEqual(report['failed_contacts'], 1)
            self.assertTrue(all(duration <= 0.25 for duration in clock.waits))

    def test_exhausted_network_retry_counts_one_failed_contact(self):
        with synthetic_database() as source, output_directory() as output:
            source_archive(source, 2)

            def fetch(*_):
                raise CollectionError('network_error')

            report = run(source, output, fetch)
            self.assertEqual(report['request_attempts'], 6)
            self.assertEqual(report['failed_contacts'], 2)
            self.assertEqual(report['verified_total'], 0)

    def test_stop_file_interrupts_retry_wait_and_resume(self):
        with synthetic_database() as source, output_directory() as output:
            source_archive(source)
            clock = Clock()
            calls = []

            def fetch(key, ident):
                calls.append(ident)
                if ident == 1:
                    return detail(ident)
                error = CollectionError('http_429')
                error.retry_after = 60
                raise error

            def stop():
                if len(calls) >= 2 and clock.now >= 1.5:
                    (output / 'STOP').write_text('')
                return False

            report = run(source, output, fetch, clock=clock, stop_requested=stop)
            self.assertEqual(report['status'], 'cancelled')
            self.assertEqual(calls, [1, 2])
            self.assertLess(clock.now, 2)
            self.assertEqual(report['verified_total'], 1)
            (output / 'STOP').unlink()
            resumed = run(source, output)
            self.assertEqual(resumed['verified_total'], 3)
            self.assertEqual(resumed['skipped'], 1)

    def test_final_attempt_retry_after_applies_to_next_contact(self):
        with synthetic_database() as source, output_directory() as output:
            source_archive(source, 2)
            clock = Clock()
            calls = []

            def fetch(key, ident):
                calls.append((ident, clock()))
                if ident == 1:
                    error = CollectionError('http_429')
                    error.retry_after = 30
                    raise error
                return detail(ident)

            report = run(source, output, fetch, clock=clock, max_attempts=1)
            self.assertEqual(report['status'], 'completed_with_failures')
            self.assertEqual([ident for ident, _ in calls], [1, 2])
            self.assertGreaterEqual(calls[1][1] - calls[0][1], 30)

    def test_duplicate_token_cannot_be_saved_for_another_contact(self):
        with synthetic_database() as source, output_directory() as output:
            source_archive(source)
            report = run(source, output, lambda key, ident: detail(ident, 'SYNTHETIC_SHARED_TOKEN'))
            self.assertEqual(report['error_code'], 'token_collision')
            self.assertEqual(report['verified_total'], 1)
            self.assertEqual(report['request_attempts'], 2)

    def test_unknown_exception_and_invalid_args_never_echo_secrets(self):
        with synthetic_database() as source, output_directory() as output:
            source_archive(source)

            def fetch(*_):
                raise RuntimeError('https://example.invalid/?key=' + KEY)

            report = run(source, output, fetch)
            self.assertEqual(report['error_code'], 'internal_failure')
            self.assertNotIn(KEY, (output / 'progress.json').read_text())
            self.assertNotIn(KEY.encode(), (output / 'links.sqlite').read_bytes())
            stdout, stderr = io.StringIO(), io.StringIO()
            with redirect_stdout(stdout), redirect_stderr(stderr):
                code = bulk.main(['--unexpected-secret=' + KEY])
            self.assertEqual(code, 1)
            self.assertNotIn(KEY, stdout.getvalue() + stderr.getvalue())
            self.assertEqual(json.loads(stdout.getvalue())['error_code'], 'invalid_arguments')

    def test_lock_prevents_another_writer_and_releases_after_exit(self):
        with output_directory() as output:
            with bulk.writer_lock(output):
                with self.assertRaisesRegex(bulk.BulkError, '^collector_already_running$'):
                    with bulk.writer_lock(output):
                        self.fail('second writer')
            with bulk.writer_lock(output):
                pass

    def test_prompt_once_for_full_run_key_not_in_arguments(self):
        with synthetic_database() as source, output_directory() as output:
            source_archive(source)
            prompts = []
            clock = Clock()
            report = bulk.collect(source, output, account='mv-centr',
                key_provider=lambda total, pending: prompts.append((total, pending)) or KEY,
                fetch=lambda key, ident: detail(ident), clock=clock, wait=clock.wait)
            self.assertEqual(report['status'], 'completed')
            self.assertEqual(prompts, [(3, 3)])

    def test_resume_rejects_changed_source_identity_before_network(self):
        with synthetic_database() as source, output_directory() as output:
            source_archive(source)
            run(source, output)
            with closing(sqlite3.connect(source)) as db:
                db.execute('INSERT INTO contacts VALUES (?,?)', (4, json.dumps(row(4))))
                db.commit()
            with self.assertRaisesRegex(bulk.BulkError, '^archive_metadata_mismatch$'):
                run(source, output, lambda *_: self.fail('network'))

    def test_encryption_failure_never_creates_success(self):
        with synthetic_database() as source, output_directory() as output:
            source_archive(source)
            with patch.object(bulk, 'protect_url', side_effect=StorageError('private_link_crypto_failed')):
                report = run(source, output)
            self.assertEqual(report['error_code'], 'private_link_crypto_failed')
            self.assertEqual(count(output, 'links'), 0)
            self.assertEqual(count(output, 'contact_state'), 0)
            resumed = run(source, output)
            self.assertEqual(resumed['verified_total'], 3)

    def test_source_hardlink_cannot_be_used_for_progress_or_database(self):
        for name in ('links.sqlite', 'progress.json.tmp', 'collector.lock'):
            with self.subTest(name=name), synthetic_database() as source, output_directory() as output:
                source_archive(source)
                before = source.read_bytes()
                os.link(source, output / name)
                with self.assertRaisesRegex(bulk.BulkError, '^source_output_overlap$'):
                    run(source, output, lambda *_: self.fail('network'))
                self.assertEqual(source.read_bytes(), before)

    def test_existing_preflight_output_is_not_modified_in_place(self):
        with synthetic_database() as source, output_directory() as output:
            source_archive(source)
            database = output / 'links.sqlite'
            with closing(sqlite3.connect(database)) as db:
                db.execute('CREATE TABLE links (source_id,url_encrypted,token_digest,captured_at,source_field)')
                db.commit()
            before = database.read_bytes()
            with self.assertRaisesRegex(bulk.BulkError, '^invalid_private_archive$'):
                run(source, output, lambda *_: self.fail('network'))
            self.assertEqual(database.read_bytes(), before)

    def test_stop_before_prompt_does_not_ask_for_key(self):
        with synthetic_database() as source, output_directory() as output:
            source_archive(source)
            (output / 'STOP').write_text('')
            report = bulk.collect(source, output, account='mv-centr',
                key_provider=lambda *_: self.fail('prompt'), fetch=lambda *_: self.fail('network'))
            self.assertEqual(report['status'], 'cancelled')
            self.assertEqual(report['request_attempts'], 0)

    def test_excessive_retry_after_stops_instead_of_retrying_early(self):
        with synthetic_database() as source, output_directory() as output:
            source_archive(source)

            def fetch(*_):
                error = CollectionError('http_429')
                error.retry_after = 172800
                raise error

            report = run(source, output, fetch)
            self.assertEqual(report['error_code'], 'retry_after_excessive')
            self.assertEqual(report['request_attempts'], 1)
            self.assertEqual(report['failed_contacts'], 1)

    def test_interrupted_run_preserves_committed_success_for_resume(self):
        with synthetic_database() as source, output_directory() as output:
            source_archive(source)

            def fetch(key, ident):
                if ident == 2:
                    raise KeyboardInterrupt()
                return detail(ident)

            report = run(source, output, fetch)
            self.assertEqual(report['status'], 'cancelled')
            self.assertEqual(report['verified_total'], 1)
            calls = []
            report = run(source, output, lambda key, ident: calls.append(ident) or detail(ident))
            self.assertEqual(calls, [2, 3])
            self.assertEqual(report['verified_total'], 3)

    def test_failed_state_write_rolls_back_version_and_does_not_skip_resume(self):
        with synthetic_database() as source, output_directory() as output:
            source_archive(source, 1)
            run(source, output)
            with closing(sqlite3.connect(output / 'links.sqlite')) as db:
                db.execute('''CREATE TRIGGER fail_synthetic_state BEFORE UPDATE ON contact_state
                    BEGIN SELECT RAISE(ABORT, 'SYNTHETIC_SECRET_DO_NOT_LOG'); END''')
                db.commit()
            report = run(source, output, refresh=True)
            self.assertEqual(report['error_code'], 'internal_failure')
            self.assertEqual(count(output, 'links'), 1)
            self.assertEqual(count(output, 'contact_state'), 1)
            with closing(sqlite3.connect(output / 'links.sqlite')) as db:
                db.execute('DROP TRIGGER fail_synthetic_state')
                db.commit()
            report = run(source, output, refresh=True)
            self.assertEqual(report['status'], 'completed')
            self.assertEqual(count(output, 'links'), 2)


if __name__ == '__main__':
    unittest.main()

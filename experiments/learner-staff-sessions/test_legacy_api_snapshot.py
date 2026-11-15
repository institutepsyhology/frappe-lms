"""Offline synthetic fixtures only: no network, account changes, or real keys."""
from contextlib import closing, contextmanager, redirect_stdout
from http.client import IncompleteRead
import io
import json
from pathlib import Path
import sqlite3
import unittest
from unittest.mock import patch
from urllib.parse import quote
import uuid

import legacy_api_snapshot as snapshot


KEY = 'SYNTHETIC_KEY_ONLY_38px%!?'
PASSWORD = 'SYNTHETIC_PRIVATE_PASSWORD_91'


@contextmanager
def folder():
    root = Path(__file__).resolve().parents[3] / 'exports'
    root.mkdir(exist_ok=True)
    directory = root / ('.synthetic-snapshot-' + uuid.uuid4().hex)
    directory.mkdir()
    try:
        yield directory
    finally:
        # Only this test's freshly created flat fixture files, never recursive.
        for path in directory.iterdir():
            if path.is_file():
                path.unlink()
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


def response(value, status=200, retry_after=None):
    body = value if isinstance(value, bytes) else json.dumps(value).encode()
    return snapshot.Response(status, body, retry_after)


def run(directory, fetch, resources=None, **options):
    clock = options.pop('clock', Clock())
    return snapshot.collect(directory, key=KEY, fetch=fetch,
        resources=resources or snapshot.RESOURCES[:1], clock=clock, wait=clock.wait, **options)


def rows(directory, query):
    with closing(sqlite3.connect(directory / 'snapshot.sqlite')) as db:
        return db.execute(query).fetchall()


class SnapshotTests(unittest.TestCase):
    def test_link_progress_exposes_only_bounded_numeric_rate(self):
        with folder() as output:
            ident = 'c' * 32
            child = output / ('links-' + ident)
            child.mkdir()
            path = child / 'progress.json'
            try:
                path.write_text(json.dumps({'current_requests_per_second':2.5,
                    'target_requests_per_second':float('nan'),'key':KEY}),encoding='utf-8')
                self.assertEqual(snapshot.read_link_progress(output,ident),{'current_requests_per_second':2.5})
            finally:
                path.unlink()
                child.rmdir()

    def test_fast_link_rate_is_explicitly_forwarded_to_child(self):
        with folder() as output:
            seen = []
            def link_collector(*args,**options):
                seen.append(options['requests_per_second'])
                return {'status':'completed'}
            report = run(output,lambda key,resource,page,*rest:
                response([{'id_contact':1}]) if page==0 else response([]),
                collect_links=True,link_collector=link_collector,link_requests_per_second=3)
            self.assertEqual(seen,[3])
            self.assertEqual(report['links_status'],'completed')

    def test_live_bold_empty_markers_keep_resource_binding(self):
        examples = [('contacts', 'No items where found for model <b></b>'),
                    ('training', 'No items where found for model <b>training</b>'),
                    ('trainingAccess', 'No items where found for model <b>trainingAccess</b>')]
        for resource, text in examples:
            with self.subTest(resource=resource):
                self.assertEqual(snapshot.parse_rows(text.encode(), snapshot.INVENTORY[resource]), [])
        with self.assertRaisesRegex(snapshot.SnapshotError, '^unexpected_structure$'):
            snapshot.parse_rows(b'No items where found for model <b>employee</b>', snapshot.INVENTORY['contacts'])
        with self.assertRaises(snapshot.SnapshotError):
            snapshot.parse_rows(b'<html>No items where found for model <b></b></html>', snapshot.INVENTORY['contacts'])

    def test_uncheckable_encoding_is_not_archived_with_encoded_key(self):
        encoded = quote(KEY, safe='').encode('ascii')
        with folder() as output:
            report = run(output, lambda *_: snapshot.Response(200, b'\xff' + encoded))
            self.assertEqual(report['error_code'], 'unverifiable_encoding')
            self.assertEqual(rows(output, 'SELECT COUNT(*) FROM pages')[0][0], 0)
            self.assertNotIn(encoded, (output / 'snapshot.sqlite').read_bytes())

    def test_bare_record_with_foreign_source_is_rejected(self):
        with self.assertRaisesRegex(snapshot.SnapshotError, '^wrong_source$'):
            snapshot.parse_rows(json.dumps({'id_contact': 1, 'source': 'https://mastervision.autoweboffice.ru'}).encode(),
                                snapshot.INVENTORY['contacts'])

    def test_foreign_model_end_marker_does_not_complete_contacts(self):
        with folder() as output:
            def fetch(key, resource, page, size, sort):
                return response([{'id_contact': 1}]) if page == 0 else response(b'No items where found for model employee')
            report = run(output, fetch)
            self.assertEqual(report['resources']['contacts']['status'], 'partial')
            self.assertEqual(report['resources']['contacts']['error_code'], 'unexpected_structure')
            self.assertEqual(report['status'], 'completed_with_errors')
        self.assertEqual(snapshot.parse_rows(b'No items where found for model Contact', snapshot.INVENTORY['contacts']), [])

    def test_http_denial_after_saved_rows_is_partial_not_successful_gap(self):
        for status in (403, 404):
            with self.subTest(status=status), folder() as output:
                def fetch(key, resource, page, size, sort):
                    return response([{'id_contact': 1}]) if page == 0 else response({}, status=status)

                report = run(output, fetch)
                self.assertEqual(report['resources']['contacts']['status'], 'partial')
                self.assertEqual(report['resources']['contacts']['error_code'], 'http_' + str(status))
                self.assertEqual(report['resources']['contacts']['rows'], 1)
                self.assertEqual(report['status'], 'completed_with_errors')

    def test_encrypted_pages_index_pagination_and_untrusted_links(self):
        with folder() as output:
            calls, clock = [], Clock()

            def fetch(key, resource, page, size, sort):
                self.assertEqual(key, KEY)
                calls.append((resource, page, size, sort, clock()))
                return response([{'id_contact': str(page + 1), 'password': PASSWORD,
                    'link_personal_auth': 'SYNTHETIC_UNTRUSTED_LINK'}] if page < 2 else [])

            report = run(output, fetch, clock=clock)
            self.assertEqual(report['status'], 'completed_with_gaps')
            self.assertEqual(report['resources']['contacts']['status'], 'complete')
            self.assertEqual([call[1] for call in calls], [0, 1, 2])
            self.assertEqual(calls[0][2:4], (100, 'id_contact ASC'))
            self.assertTrue(all(calls[i][4] - calls[i - 1][4] >= 1 for i in (1, 2)))
            captured = rows(output, 'SELECT resource,page,raw_encrypted FROM pages ORDER BY version_id')
            self.assertEqual(snapshot.unprotect_page(captured[0][0], captured[0][1], captured[0][2])['raw'],
                response([{'id_contact': '1', 'password': PASSWORD,
                    'link_personal_auth': 'SYNTHETIC_UNTRUSTED_LINK'}]).body)
            with closing(sqlite3.connect(output / 'contacts.sqlite')) as db:
                records = db.execute('SELECT id,record_json FROM contacts ORDER BY id').fetchall()
            self.assertEqual([row[0] for row in records], [1, 2])
            self.assertEqual(json.loads(records[0][1]),
                {'source': snapshot.API_ORIGIN, 'contact': {'id': 1}})
            self.assertEqual(report['list_personal_links'], 'untrusted_not_for_login')
            for file in output.iterdir():
                self.assertNotIn(KEY.encode(), file.read_bytes())
                self.assertNotIn(PASSWORD.encode(), file.read_bytes())

    def test_repeated_page_is_partial_and_does_not_advance(self):
        with folder() as output:
            report = run(output, lambda *args: response([{'id_contact': 1}]))
            self.assertEqual(report['resources']['contacts']['status'], 'partial')
            self.assertEqual(report['resources']['contacts']['error_code'], 'repeated_page')
            self.assertEqual(rows(output, 'SELECT COUNT(*) FROM row_ids')[0][0], 1)
            self.assertEqual(rows(output, 'SELECT next_page FROM resource_state')[0][0], 1)

    def test_duplicate_ids_across_and_within_pages(self):
        for pages in (([{'id_contact': 1}], [{'id_contact': 1, 'x': 2}]),
                      ([{'id_contact': 1}, {'id_contact': 1}],)):
            with self.subTest(pages=len(pages)), folder() as output:
                report = run(output, lambda key, resource, page, *rest: response(pages[page]))
                self.assertEqual(report['resources']['contacts']['error_code'], 'duplicate_ids')

    def test_resume_preserves_failure_and_success_prefix(self):
        with folder() as output:
            def first(key, resource, page, *rest):
                return response([{'id_contact': 1}]) if page == 0 else response(12)
            run(output, first)
            initial = rows(output, 'SELECT raw_encrypted FROM pages ORDER BY version_id')
            calls = []
            def retry(key, resource, page, *rest):
                calls.append(page)
                return response([{'id_contact': 2}]) if page == 1 else response([])
            report = run(output, retry)
            self.assertEqual(calls, [1, 2])
            self.assertEqual(report['resources']['contacts']['rows'], 2)
            self.assertEqual(rows(output, 'SELECT raw_encrypted FROM pages ORDER BY version_id')[:2], initial)

    def test_strange_shapes_retained_encrypted_not_coerced(self):
        for payload in (12, True, None, {'unknown': []}, [1], {'data': [], 'items': []}):
            with self.subTest(payload=type(payload).__name__), folder() as output:
                report = run(output, lambda *args: response(payload))
                self.assertEqual(report['resources']['contacts']['error_code'], 'unexpected_structure')
                self.assertEqual(rows(output, 'SELECT COUNT(*) FROM pages')[0][0], 1)

    def test_empty_first_is_inferred_but_known_empty_text_after_rows_is_end(self):
        with folder() as output:
            report = run(output, lambda *args: response(b'No items where found for model contacts'))
            self.assertEqual(report['resources']['contacts']['status'], 'empty_inferred')
        with folder() as output:
            report = run(output, lambda key, resource, page, *rest:
                response([{'id_contact': 1}]) if page == 0 else response('No items where found for model '))
            self.assertEqual(report['resources']['contacts']['status'], 'complete')

    def test_unavailable_continues_authentication_stops(self):
        for status, expected in ((403, 'access_denied'), (404, 'unavailable')):
            with self.subTest(status=status), folder() as output:
                calls = []
                def fetch(key, resource, *rest):
                    calls.append(resource)
                    return response({}, status) if resource == 'contacts' else response([])
                report = run(output, fetch, snapshot.RESOURCES[:2])
                self.assertEqual(report['resources']['contacts']['status'], expected)
                self.assertEqual(calls, ['contacts', 'employee'])
        with folder() as output:
            report = run(output, lambda *args: response({}, 401), snapshot.RESOURCES[:2])
            self.assertEqual(report['status'], 'stopped')
            self.assertEqual(report['error_code'], 'http_401')
            self.assertEqual(report['request_attempts'], 1)

    def test_ten_errors_stop_and_success_resets_counter(self):
        with folder() as output:
            report = run(output, lambda *args: response(12), snapshot.RESOURCES[:11])
            self.assertEqual(report['error_code'], 'failure_limit')
            self.assertEqual(report['request_attempts'], 10)
        with folder() as output:
            success_resource = snapshot.RESOURCES[8].name
            report = run(output, lambda key, resource, *rest:
                response([]) if resource == success_resource else response(12), snapshot.RESOURCES[:12])
            self.assertNotEqual(report['error_code'], 'failure_limit')
            self.assertEqual(report['consecutive_errors'], 3)

    def test_raw_and_encoded_and_json_escaped_key_leaks_stop_without_save(self):
        for leaked in (KEY, quote(KEY, safe=''), quote(quote(KEY, safe=''), safe='')):
            with self.subTest(leaked=leaked[:1]), folder() as output:
                report = run(output, lambda *args: response([{'id_contact': 1, 'value': leaked}]))
                self.assertEqual(report['error_code'], 'api_key_in_response')
                self.assertEqual(rows(output, 'SELECT COUNT(*) FROM pages')[0][0], 0)
        with folder() as output:
            escaped = ''.join('\\u%04x' % ord(char) for char in KEY)
            report = run(output, lambda *args: response(('[{"id_contact":1,"x":"' + escaped + '"}]').encode()))
            self.assertEqual(report['error_code'], 'api_key_in_response')

    def test_retry_after_and_stop_wait_are_bounded(self):
        with folder() as output:
            clock, calls = Clock(), []
            def fetch(*args):
                calls.append(clock())
                return response({}, 429, '2') if len(calls) == 1 else response([])
            run(output, fetch, clock=clock)
            self.assertGreaterEqual(calls[1] - calls[0], 2)
            self.assertLessEqual(max(clock.waits), 0.25)
        with folder() as output:
            clock = Clock()
            report = run(output, lambda *args: response({}, 503, '100'), clock=clock,
                stop_requested=lambda: clock() > 0.5)
            self.assertEqual(report['status'], 'cancelled')
            self.assertLessEqual(clock(), 0.75)

    def test_retry_after_final_attempt_applies_before_next_resource(self):
        with folder() as output:
            calls, clock = [], Clock()
            def fetch(key, resource, *rest):
                calls.append((resource, clock()))
                return response({}, 429, '4') if resource == 'contacts' else response([])
            run(output, fetch, snapshot.RESOURCES[:2], clock=clock, max_attempts=1)
            self.assertEqual([call[0] for call in calls], ['contacts', 'employee'])
            self.assertGreaterEqual(calls[1][1] - calls[0][1], 4)

    def test_intermediate_http_response_is_retained_and_namespaced(self):
        with folder() as output:
            responses = iter([response({'x': PASSWORD}, 503), response([])])
            run(output, lambda *args: next(responses))
            captures = rows(output, 'SELECT resource,page,parse_code,raw_encrypted FROM pages ORDER BY version_id')
            self.assertEqual([item[2] for item in captures], ['http_503', 'empty_inferred'])
            decrypted = snapshot.unprotect_page(captures[0][0], captures[0][1], captures[0][3])
            self.assertEqual(json.loads(decrypted['raw']), {'x': PASSWORD})
            with self.assertRaises(Exception):
                snapshot.unprotect_page('employee', 0, captures[0][3])

    def test_wrong_source_stops_without_archiving_foreign_data(self):
        with folder() as output:
            report = run(output, lambda *args: response({'source': 'https://example.invalid', 'data': []}))
            self.assertEqual(report['error_code'], 'wrong_source')
            self.assertEqual(rows(output, 'SELECT COUNT(*) FROM pages')[0][0], 0)

    def test_metadata_mismatch_never_fetches_or_changes_existing_snapshot(self):
        with folder() as output:
            run(output, lambda *args: response([]))
            before = (output / 'snapshot.sqlite').read_bytes()
            with self.assertRaises(snapshot.SnapshotError):
                run(output, lambda *args: self.fail('must not fetch'), page_size=50)
            self.assertEqual((output / 'snapshot.sqlite').read_bytes(), before)

    def test_empty_or_denied_resource_is_rechecked_on_resume(self):
        for first in (response([]), response({}, 403)):
            with self.subTest(status=first.status), folder() as output:
                run(output, lambda *args: first)
                report = run(output, lambda key, resource, page, *rest:
                    response([{'id_contact': 1}]) if page == 0 else response([]))
                self.assertEqual(report['resources']['contacts']['status'], 'complete')
                self.assertEqual(rows(output, 'SELECT COUNT(*) FROM pages')[0][0], 3)

    def test_scope_arguments_lock_and_output_are_fail_closed(self):
        with folder() as output:
            with self.assertRaises(snapshot.SnapshotError):
                snapshot.collect(output, account='mastervision', key=KEY, fetch=lambda *args: self.fail())
            with self.assertRaises(snapshot.SnapshotError):
                snapshot.collect(Path(__file__).parent, key=KEY, fetch=lambda *args: self.fail())
            with snapshot.writer_lock(output):
                with self.assertRaises(Exception):
                    run(output, lambda *args: self.fail())

    def test_key_provider_once_and_forwarded_to_optional_bulk_in_memory(self):
        with folder() as output:
            supplied, forwarded = [], []
            def provider():
                supplied.append(1)
                return KEY
            def links(source, destination, **options):
                forwarded.append((source, destination, options))
                return {'status': 'completed', 'verified_total': 1}
            clock = Clock()
            report = snapshot.collect(output, key_provider=provider, resources=snapshot.RESOURCES[:1],
                fetch=lambda key, resource, page, *rest: response([{'id_contact': 2}]) if page == 0 else response([]),
                collect_links=True, link_collector=links, clock=clock, wait=clock.wait)
            self.assertEqual(supplied, [1])
            self.assertEqual(forwarded[0][2]['key'], KEY)
            self.assertEqual(forwarded[0][0], output / 'contacts.sqlite')
            self.assertEqual(report['links_status'], 'completed')
            self.assertNotIn(KEY, json.dumps(report))

    def test_link_failure_is_not_announced_as_completed_and_phase_is_reported(self):
        for status in ('stopped_consecutive_failures', 'stopped_fatal_error', 'completed_with_failures',
                       'cancelled', 'unexpected'):
            with self.subTest(status=status), folder() as output:
                phases = []
                report = run(output, lambda key, resource, page, *rest:
                    response([{'id_contact': 1}]) if page == 0 else response([]), collect_links=True,
                    link_collector=lambda *args, **options: {'status': status},
                    on_progress=lambda value: phases.append(value['status']))
                self.assertIn('collecting_links', phases)
                self.assertEqual(report['status'], 'cancelled' if status == 'cancelled' else 'stopped')
                self.assertEqual(report['error_code'], 'link_collection_failed')
                self.assertEqual(report['links_status'], status if status in snapshot.LINK_STATUSES else 'incomplete')

    def test_optional_link_progress_is_sanitized_to_phase_and_counts(self):
        with folder() as output:
            ident = 'a' * 32
            child = output / ('links-' + ident)
            child.mkdir()
            path = child / 'progress.json'
            try:
                path.write_text(json.dumps({'status': 'collecting', 'verified_total': 7,
                    'total_contacts': 9, 'request_attempts': 10, 'failed_contacts': -1,
                    'error_code': PASSWORD, 'key': KEY}), encoding='utf-8')
                self.assertEqual(snapshot.read_link_progress(output, ident),
                    {'status': 'collecting', 'verified_total': 7, 'total_contacts': 9, 'request_attempts': 10})
                self.assertEqual(snapshot.read_link_progress(output, '../outside'), {})
            finally:
                path.unlink()
                child.rmdir()

    def test_transport_fixed_origin_no_redirect_and_does_not_echo_exceptions(self):
        class Broken:
            def open(self, request, timeout):
                self.request = request
                raise OSError('SYNTHETIC_TRANSPORT_SECRET_' + KEY)
        transport = Broken()
        with patch.object(snapshot, 'build_opener', return_value=transport):
            with self.assertRaises(snapshot.SnapshotError) as raised:
                snapshot.read_page(KEY, 'contacts', 0, 100, 'id_contact ASC')
        self.assertEqual(str(raised.exception), 'network_error')
        self.assertTrue(transport.request.full_url.startswith(snapshot.API_ORIGIN + '/?'))
        self.assertEqual(transport.request.method, 'GET')

    def test_interrupted_transport_body_is_retryable_network_error(self):
        class Stream:
            code = 200
            headers = {}
            def __enter__(self):
                return self
            def __exit__(self, *args):
                return False
            def geturl(self):
                return self.url
            def read(self, size):
                raise IncompleteRead(b'SYNTHETIC_NOT_FOR_LOGS', 100)
        class Transport:
            def open(self, request, timeout):
                stream = Stream()
                stream.url = request.full_url
                return stream
        with patch.object(snapshot, 'build_opener', return_value=Transport()):
            with self.assertRaises(snapshot.SnapshotError) as raised:
                snapshot.read_page(KEY, 'contacts', 0, 100, 'id_contact ASC')
        self.assertEqual(str(raised.exception), 'network_error')

    def test_cli_never_echoes_accidental_key_argument(self):
        output = io.StringIO()
        with redirect_stdout(output):
            self.assertEqual(snapshot.main(['--key', KEY]), 1)
        self.assertNotIn(KEY, output.getvalue())
        self.assertEqual(json.loads(output.getvalue())['error_code'], 'invalid_arguments')


if __name__ == '__main__':
    unittest.main()

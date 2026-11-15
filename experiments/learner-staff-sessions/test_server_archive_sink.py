"""Synthetic receiver tests; no source credentials or production calls."""
import base64
from contextlib import closing
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import types
import unittest
from unittest.mock import patch
import uuid
import zlib

from cryptography.fernet import Fernet

import server_archive_sink as sink


SNAPSHOT = 'a' * 32
STAMP = '2026-11-16T00:00:00+00:00'
LINK_METADATA = {'schema': 'mvcentr-individual-links-v1', 'account': 'mv-centr',
                 'origin': sink.API_ORIGIN, 'source_ids_sha256': 'b' * 64,
                 'source_count': '2'}
PAGE_METADATA = {'format': 'mvcentr-legacy-api-snapshot-v1', 'account': 'mv-centr',
                 'source': sink.API_ORIGIN, 'page_size': '100', 'snapshot': SNAPSHOT}


def canonical(value):
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(',', ':')).encode()


def link_payload(version=1, source_id=10, token='synthetic-only-token'):
    return {'version_id': version, 'source_id': source_id,
            'url': 'https://shop.mv-centr.ru/personal/auth/secure-login?uid='
                   + str(source_id) + '&vc=' + token,
            'captured_at': STAMP, 'source_field': 'link_personal_auth',
            'capture_origin': 'individual_detail',
            'token_digest': hashlib.sha256(token.encode()).hexdigest()}


def page_payload(version=1, raw=b'[{"id_contact":10}]'):
    return {'version_id': version, 'module': 'mvcentr-legacy-api-snapshot-v1',
            'account': 'mv-centr', 'source': sink.API_ORIGIN, 'resource': 'contacts',
            'page': 1, 'sha256': hashlib.sha256(raw).hexdigest(), 'row_count': 1,
            'captured_at': STAMP, 'parse_code': 'accepted',
            'body_b64': base64.b64encode(zlib.compress(raw)).decode()}


def record(payload, source_id=None):
    raw = canonical(payload)
    return {'version_id': payload['version_id'], 'source_id': source_id,
            'sha256': hashlib.sha256(raw).hexdigest(),
            'payload_b64': base64.b64encode(raw).decode()}


def request(*payloads, kind='links'):
    return {'format': sink.FORMAT, 'snapshot': SNAPSHOT, 'kind': kind,
            'source_metadata': deepcopy(LINK_METADATA if kind == 'links' else PAGE_METADATA),
            'records': [record(payload, payload['source_id'] if kind == 'links' else None)
                        for payload in payloads]}


class SinkTests(unittest.TestCase):
    def test_legacy_page_zero_is_valid_but_negative_and_boolean_pages_are_not(self):
        payload=page_payload()
        payload['page']=0
        self.assertEqual(self.send(request(payload,kind='pages'))['stored_total'],1)
        for bad in (-1,True):
            payload['version_id']+=1
            payload['page']=bad
            self.assertRejected(request(payload,kind='pages'),'invalid_page')

    def setUp(self):
        # Existing workspace fixtures avoid the host's inaccessible TEMP ACLs.
        parent = Path(__file__).resolve().parents[3] / 'exports'
        parent.mkdir(exist_ok=True)
        self.temporary = parent / ('.synthetic-sink-' + uuid.uuid4().hex)
        self.temporary.mkdir()
        self.root = self.temporary / 'avo-ingest'
        self.cipher = Fernet(Fernet.generate_key())

    def tearDown(self):
        (self.temporary / 'indirect').unlink(missing_ok=True)
        if self.root.exists():
            for name in ('archive.sqlite', 'archive.sqlite-journal', 'archive.sqlite-wal', 'archive.sqlite-shm'):
                (self.root / name).unlink(missing_ok=True)
            self.root.rmdir()
        self.temporary.rmdir()

    def send(self, value, cipher=None):
        return sink.handle_request(value, root=self.root, cipher=cipher or self.cipher)

    def assertRejected(self, value, code=None):
        with self.assertRaises(sink.SinkError) as caught:
            self.send(value)
        if code:
            self.assertEqual(str(caught.exception), code)
        self.assertNotIn('synthetic-only-token', str(caught.exception))

    def test_links_commit_readback_encrypted_and_safe_ack(self):
        payload = link_payload()
        value = request(payload)
        result = self.send(value)
        self.assertEqual(result, {'format': sink.FORMAT, 'site': sink.SITE,
            'snapshot': SNAPSHOT, 'kind': 'links', 'stored_total': 1,
            'records': [{key: value['records'][0][key]
                         for key in ('version_id', 'source_id', 'sha256')}]})
        self.assertNotIn('synthetic-only-token', json.dumps(result))
        self.assertNotIn(b'synthetic-only-token', self.root.joinpath('archive.sqlite').read_bytes())

    def test_repeat_is_idempotent_and_other_version_is_preserved(self):
        first = request(link_payload())
        self.send(first)
        self.assertEqual(self.send(first)['stored_total'], 1)
        later = request(link_payload(version=2, token='synthetic-new-token'))
        self.assertEqual(self.send(later)['stored_total'], 2)
        self.assertEqual(self.send(first)['stored_total'], 2)

    def test_conflicting_version_cannot_replace_ciphertext(self):
        original = request(link_payload())
        self.send(original)
        self.assertRejected(request(link_payload(token='other-synthetic-token')), 'version_conflict')
        self.assertEqual(self.send(original)['stored_total'], 1)

    def test_status_empty_records_has_count_no_payloads(self):
        self.send(request(link_payload()))
        result = self.send(request())
        self.assertEqual(result['stored_total'], 1)
        self.assertEqual(result['records'], [])

    def test_metadata_is_stable_per_snapshot_kind(self):
        self.send(request(link_payload()))
        altered = request(link_payload(version=2))
        altered['source_metadata']['source_ids_sha256'] = 'c' * 64
        self.assertRejected(altered, 'source_metadata_conflict')

    def test_accounts_site_and_path_input_are_fixed(self):
        for field, value in [('snapshot', '../escape'), ('snapshot', 'A' * 32),
                             ('kind', 'users'), ('format', 'other')]:
            data = request(link_payload())
            data[field] = value
            self.assertRejected(data)
        for field, value in [('account', 'mastervision'), ('origin', 'https://other.invalid')]:
            data = request(link_payload())
            data['source_metadata'][field] = value
            self.assertRejected(data)
        data = request(link_payload())
        data['path'] = '/tmp/escape'
        self.assertRejected(data)

    def test_link_binding_host_path_uid_digest_and_fields(self):
        changes = [
            ('source_id', 11), ('version_id', 2), ('source_field', 'link_personal_employee'),
            ('capture_origin', 'raw_list'), ('captured_at', '2026-11-16'),
            ('token_digest', '0' * 64),
            ('url', 'https://shop.mastervision.su/personal/auth/secure-login?uid=10&vc=x'),
            ('url', 'https://shop.mv-centr.ru/personal/auth/secure-login?uid=11&vc=x'),
            ('url', 'https://shop.mv-centr.ru/personal/auth/secure-login?uid=10&uid=10&vc=x'),
            ('url', 'https://shop.mv-centr.ru/personal/auth/secure-login?uid=10&vc=x#fragment'),
        ]
        for field, value in changes:
            with self.subTest(field=field, value=value if field != 'url' else 'redacted'):
                payload = link_payload()
                payload[field] = value
                data = request(payload)
                if field == 'source_id':
                    data['records'][0]['source_id'] = 10
                if field == 'version_id':
                    data['records'][0]['version_id'] = 1
                self.assertRejected(data)

    def test_envelope_digest_rejects_modified_wire_payload(self):
        data = request(link_payload())
        data['records'][0]['sha256'] = '0' * 64
        self.assertRejected(data, 'payload_hash_mismatch')

    def test_wrong_record_types_duplicates_and_bounds(self):
        for value in [True, 0, -1, 2**63, '1']:
            data = request(link_payload())
            data['records'][0]['version_id'] = value
            self.assertRejected(data)
        data = request(link_payload())
        data['records'].append(deepcopy(data['records'][0]))
        self.assertRejected(data, 'invalid_records')
        data['records'] = data['records'] * 51
        self.assertRejected(data)

    def test_base64_json_shape_and_duplicates_are_rejected(self):
        for raw in [b'{', b'[]', b'{"a":1,"a":2}', b'{"bad":NaN}']:
            data = request(link_payload())
            data['records'][0]['payload_b64'] = base64.b64encode(raw).decode()
            data['records'][0]['sha256'] = hashlib.sha256(raw).hexdigest()
            self.assertRejected(data)
        data['records'][0]['payload_b64'] = '%%%'
        self.assertRejected(data)

    def test_bounded_request_and_record(self):
        data = request(link_payload())
        with patch.object(sink, 'MAX_REQUEST', 10):
            self.assertRejected(data, 'request_too_large')
        with patch.object(sink, 'MAX_PAYLOAD', 10):
            self.assertRejected(data, 'payload_too_large')

    def test_pages_raw_data_reencrypted_and_separate_from_links(self):
        self.send(request(link_payload()))
        result = self.send(request(page_payload(), kind='pages'))
        self.assertEqual(result['stored_total'], 1)
        self.assertIsNone(result['records'][0]['source_id'])
        self.assertEqual(self.send(request())['stored_total'], 1)

    def test_pages_wrong_binding_and_corrupt_compression(self):
        for field, value in [('account', 'other'), ('source', 'https://wrong.invalid'),
                             ('module', 'wrong'), ('page', -1), ('row_count', -1),
                             ('resource', '../../escape'), ('sha256', '0' * 64),
                             ('body_b64', base64.b64encode(b'not zlib').decode())]:
            payload = page_payload()
            payload[field] = value
            self.assertRejected(request(payload, kind='pages'))

    def test_page_bomb_trailing_stream_and_declared_hash_checked(self):
        payload = page_payload(raw=b'x' * 1000)
        with patch.object(sink, 'MAX_PAGE_RAW', 99):
            self.assertRejected(request(payload, kind='pages'), 'page_too_large')
        payload = page_payload()
        packed = base64.b64decode(payload['body_b64']) + b'trailing'
        payload['body_b64'] = base64.b64encode(packed).decode()
        self.assertRejected(request(payload, kind='pages'), 'invalid_page_body')

    def test_batch_failure_is_atomic(self):
        self.send(request(link_payload(version=2)))
        data = request(link_payload(version=1), link_payload(version=2, token='new-synthetic-token'))
        self.assertRejected(data, 'version_conflict')
        self.assertEqual(self.send(request())['stored_total'], 1)

    def test_readback_encryption_failure_never_acknowledges(self):
        class WrongCipher:
            encrypt = self.cipher.encrypt
            def decrypt(self, value):
                raise RuntimeError('private payload must never be echoed')
        self.assertRejectedCipher(request(link_payload()), WrongCipher(), 'readback_failed')
        # The committed row survives a lost acknowledgement and can be retried.
        self.assertEqual(self.send(request(link_payload()))['stored_total'], 1)

    def assertRejectedCipher(self, value, cipher, code):
        with self.assertRaises(sink.SinkError) as caught:
            self.send(value, cipher=cipher)
        self.assertEqual(str(caught.exception), code)

    def test_ciphertext_cannot_be_swapped_between_rows(self):
        first, second = link_payload(), link_payload(version=2, source_id=11, token='second-token')
        self.send(request(first, second))
        with closing(sqlite3.connect(self.root / 'archive.sqlite')) as db:
            rows = db.execute('SELECT version_id,payload_encrypted FROM records ORDER BY version_id').fetchall()
            with db:
                db.execute('UPDATE records SET payload_encrypted=? WHERE version_id=1', (rows[1][1],))
        self.assertRejected(request(first), 'readback_failed')

    @unittest.skipIf(os.name == 'nt', 'Unix filesystem permissions')
    def test_private_directory_database_and_no_symlink_follow(self):
        self.send(request(link_payload()))
        self.assertEqual(self.root.stat().st_mode & 0o777, 0o700)
        self.assertEqual((self.root / 'archive.sqlite').stat().st_mode & 0o777, 0o600)
        wrong = self.temporary / 'indirect'
        wrong.symlink_to(self.root, target_is_directory=True)
        with self.assertRaises(sink.SinkError):
            sink.handle_request(request(), root=wrong, cipher=self.cipher)

    def test_main_failure_prints_only_safe_code(self):
        import io
        from contextlib import redirect_stdout
        output = io.StringIO()
        with patch.object(sink, 'runtime_archive', side_effect=RuntimeError('SENSITIVE')), \
             patch.object(sink.sys, 'stdin', io.TextIOWrapper(io.BytesIO(canonical(request())))), \
             redirect_stdout(output):
            result = sink.main()
        self.assertEqual(result, 2)
        self.assertEqual(json.loads(output.getvalue()), {'format': sink.FORMAT, 'error': 'archive_failed'})
        self.assertNotIn('SENSITIVE', output.getvalue())

    def fake_frappe(self, *, key=None, site=sink.SITE):
        events = []
        fake = types.SimpleNamespace(
            init=lambda **kwargs: events.append(('init', kwargs)),
            destroy=lambda: events.append(('destroy', None)),
            conf={'encryption_key': key}, local=types.SimpleNamespace(site=site),
            get_site_path=lambda *parts: str(self.root))
        return fake, events

    def test_runtime_uses_existing_fixed_site_key_without_connect_or_files(self):
        key = Fernet.generate_key()
        fake, events = self.fake_frappe(key=key.decode())
        with patch.dict('sys.modules', {'frappe': fake}):
            root, cipher = sink.runtime_archive()
        self.assertEqual(root, self.root)
        encrypted = cipher.encrypt(b'synthetic-test-only')
        self.assertEqual(Fernet(key).decrypt(encrypted), b'synthetic-test-only')
        self.assertEqual(events, [('init', {'site': sink.SITE}), ('destroy', None)])
        self.assertFalse(self.root.exists())

    def test_runtime_never_creates_a_missing_or_invalid_key(self):
        for key in (None, '', 'not-a-valid-key', True):
            fake, events = self.fake_frappe(key=key)
            with patch.dict('sys.modules', {'frappe': fake}), \
                 self.assertRaises(sink.SinkError) as caught:
                sink.runtime_archive()
            self.assertEqual(str(caught.exception), 'existing_site_key_required')
            self.assertEqual(events[-1], ('destroy', None))
            self.assertFalse(self.root.exists())

    def test_wrong_initialized_site_is_rejected(self):
        fake, _ = self.fake_frappe(key=Fernet.generate_key(), site='my-lk.mastervision.su')
        with patch.dict('sys.modules', {'frappe': fake}), self.assertRaises(sink.SinkError) as caught:
            sink.runtime_archive()
        self.assertEqual(str(caught.exception), 'wrong_site')

    def test_main_bounds_input_before_reading_site_key(self):
        import io
        from contextlib import redirect_stdout
        output = io.StringIO()
        with patch.object(sink, 'MAX_REQUEST', 10), \
             patch.object(sink, 'runtime_archive') as runtime, \
             patch.object(sink.sys, 'stdin', io.TextIOWrapper(io.BytesIO(b' ' * 20))), \
             redirect_stdout(output):
            self.assertEqual(sink.main(), 2)
        runtime.assert_not_called()
        self.assertEqual(json.loads(output.getvalue())['error'], 'request_too_large')


if __name__ == '__main__':
    unittest.main()

"""Synthetic encrypted MVC contact-page reader fixtures only."""
import base64
from contextlib import closing
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sqlite3
import unittest
from unittest.mock import patch
import uuid
import zlib

from cryptography.fernet import Fernet

import mvcentr_archive_reader as reader
import server_archive_sink as sink


SNAPSHOT = 'a' * 32
STAMP = '2026-11-16T00:00:00+00:00'


def fingerprint(ids):
    value = hashlib.sha256(reader.API_ORIGIN.encode('ascii'))
    for ident in ids:
        value.update(str(ident).encode('ascii') + b'\n')
    return value.hexdigest()


def wrapped(payload):
    raw = sink.canonical_json(payload)
    return {'version_id': payload['version_id'], 'source_id': None,
            'sha256': hashlib.sha256(raw).hexdigest(),
            'payload_b64': base64.b64encode(raw).decode()}


def page(rows, *, version=1, page=0, resource='contacts', code='accepted', raw=None):
    raw = sink.canonical_json(rows) if raw is None else raw
    return {'version_id': version, 'module': reader.PAGE_FORMAT, 'account': reader.ACCOUNT,
        'source': reader.API_ORIGIN, 'resource': resource, 'page': page,
        'sha256': hashlib.sha256(raw).hexdigest(), 'row_count': len(rows),
        'captured_at': STAMP, 'parse_code': code,
        'body_b64': base64.b64encode(zlib.compress(raw)).decode()}


class ReaderTests(unittest.TestCase):
    def setUp(self):
        parent = Path(__file__).resolve().parents[3] / 'exports'
        self.root = parent / ('.synthetic-archive-reader-' + uuid.uuid4().hex)
        self.cipher = Fernet(Fernet.generate_key())
        self.database = self.root / 'archive.sqlite'
        self.pages = {'format': reader.PAGE_FORMAT, 'account': reader.ACCOUNT,
                      'source': reader.API_ORIGIN, 'page_size': '100', 'snapshot': SNAPSHOT}
        self.links = {'schema': reader.LINK_SCHEMA, 'account': reader.ACCOUNT,
                      'origin': reader.API_ORIGIN, 'source_ids_sha256': fingerprint([10, 11]),
                      'source_count': '2'}

    def tearDown(self):
        for name in ('archive.sqlite', 'archive.sqlite-journal', 'archive.sqlite-wal', 'archive.sqlite-shm'):
            (self.root / name).unlink(missing_ok=True)
        if self.root.exists():
            self.root.rmdir()

    def initialize(self):
        sink.handle_request({'format': reader.FORMAT, 'snapshot': SNAPSHOT,
            'kind': 'links', 'source_metadata': self.links, 'records': []}, root=self.root, cipher=self.cipher)

    def store(self, *payloads):
        if not self.database.exists():
            self.initialize()
        sink.handle_request({'format': reader.FORMAT, 'snapshot': SNAPSHOT,
            'kind': 'pages', 'source_metadata': self.pages,
            'records': [wrapped(payload) for payload in payloads]}, root=self.root, cipher=self.cipher)

    def read(self, cipher=None, snapshot=SNAPSHOT):
        return list(reader.iter_contacts(self.database, cipher or self.cipher, snapshot))

    def mutate(self, sql, args=()):
        with closing(sqlite3.connect(self.database)) as db:
            with db:
                db.execute(sql, args)

    def test_actual_contact_fields_preserved_but_untrusted_personal_link_dropped(self):
        self.store(page([{'id_contact': 10, 'name': 'Synthetic One', 'password': 'SYNTHETIC_PASSWORD',
                          'not_to_write': '1', 'extra': {'nested': [1, None]},
                          'link_personal_auth': 'SYNTHETIC_UNTRUSTED_URL'},
                         {'id_contact': '11', 'spam_clicked': 1}]))
        rows = self.read()
        self.assertEqual(rows, [(1, {'id_contact': '10', 'name': 'Synthetic One',
            'password': 'SYNTHETIC_PASSWORD', 'not_to_write': '1', 'extra': {'nested': [1, None]}}),
            (1, {'id_contact': '11', 'spam_clicked': 1})])

    def test_other_resources_and_error_pages_are_verified_then_skipped(self):
        self.store(page([], version=1, resource='employee', code='http_500', raw=b'not JSON'),
                   page([{'id_contact': 10}], version=2),
                   page([], version=3, page=1, code='invalid_json', raw=b'old terminal marker'),
                   page([{'id_contact': 11}], version=4, page=1))
        self.assertEqual(self.read(), [(2, {'id_contact': '10'}), (4, {'id_contact': '11'})])

    def test_source_wrappers_and_utf8_bom_are_supported(self):
        raw = b'\xef\xbb\xbf' + sink.canonical_json({'source': reader.API_ORIGIN,
            'data': {'contacts': [{'id_contact': '10'}, {'id_contact': '11'}]}})
        self.store(page([{}, {}], raw=raw))
        self.assertEqual([row['id_contact'] for _, row in self.read()], ['10', '11'])

    def test_missing_gap_duplicate_or_out_of_order_contact_pages_are_rejected(self):
        self.store(page([{'id_contact': 10}], page=0),
                   page([{'id_contact': 11}], page=2, version=2))
        with self.assertRaisesRegex(reader.ReaderError, '^contact_page_sequence$'):
            self.read()

    def test_duplicate_contact_ids_across_pages_are_rejected(self):
        self.store(page([{'id_contact': 10}], page=0),
                   page([{'id_contact': '10'}], page=1, version=2))
        with self.assertRaisesRegex(reader.ReaderError, '^contact_id_order$'):
            self.read()

    def test_noncanonical_contact_id_is_rejected(self):
        for ident in ('01', '0', '１０', True, 0, -1, 2**63, '9223372036854775808'):
            with self.subTest(kind=type(ident).__name__):
                self.assertIdRejected(ident)

    def assertIdRejected(self, ident):
        if self.database.exists():
            self.mutate('DELETE FROM records')
        self.store(page([{'id_contact': ident}, {'id_contact': 11}]))
        with self.assertRaisesRegex(reader.ReaderError, '^invalid_contact_id$'):
            self.read()

    def test_final_source_count_and_fingerprint_must_match(self):
        self.links['source_count'] = '3'
        self.store(page([{'id_contact': 10}, {'id_contact': 11}]))
        with self.assertRaisesRegex(reader.ReaderError, '^source_count_mismatch$'):
            self.read()

    def test_final_source_fingerprint_is_checked(self):
        self.links['source_ids_sha256'] = '0' * 64
        self.store(page([{'id_contact': 10}, {'id_contact': 11}]))
        with self.assertRaisesRegex(reader.ReaderError, '^source_fingerprint_mismatch$'):
            self.read()

    def test_wrong_site_archive_and_wrong_snapshot_are_rejected(self):
        self.store(page([{'id_contact': 10}, {'id_contact': 11}]))
        with self.assertRaisesRegex(reader.ReaderError, '^invalid_snapshot$'):
            self.read(snapshot='../escape')
        with self.assertRaisesRegex(reader.ReaderError, '^invalid_metadata$'):
            self.read(snapshot='b' * 32)
        self.mutate('UPDATE archive_metadata SET value=? WHERE key=?', ('my-lk.mastervision.su', 'site'))
        with self.assertRaisesRegex(reader.ReaderError, '^wrong_source$'):
            self.read()

    def test_metadata_canonical_shape_and_binding_are_checked(self):
        self.store(page([{'id_contact': 10}, {'id_contact': 11}]))
        altered = dict(self.pages, account='mastervision')
        self.mutate('UPDATE source_metadata SET metadata_json=? WHERE kind=?',
                    (sink.canonical_json(altered).decode(), 'pages'))
        with self.assertRaisesRegex(reader.ReaderError, '^invalid_metadata$'):
            self.read()

    def test_wrong_cipher_or_swapped_ciphertext_cannot_be_read(self):
        self.store(page([{'id_contact': 10}], version=1), page([{'id_contact': 11}], version=2, page=1))
        with self.assertRaisesRegex(reader.ReaderError, '^archive_crypto_failed$'):
            self.read(cipher=Fernet(Fernet.generate_key()))
        with closing(sqlite3.connect(self.database)) as db:
            second = db.execute('SELECT payload_encrypted FROM records WHERE version_id=2').fetchone()[0]
        self.mutate('UPDATE records SET payload_encrypted=? WHERE version_id=1', (second,))
        with self.assertRaisesRegex(reader.ReaderError, '^invalid_envelope$'):
            self.read()

    def test_encrypted_raw_page_has_bounded_decompression(self):
        self.store(page([{'id_contact': 10, 'text': 'x' * 1000}, {'id_contact': 11}]))
        with patch.object(reader, 'MAX_BODY', 100), self.assertRaisesRegex(reader.ReaderError, '^page_too_large$'):
            self.read()

    def test_page_row_count_and_contact_structure_are_checked(self):
        self.store(page([{'id_contact': 10}, {'id_contact': 11}], raw=b'[]'))
        with self.assertRaisesRegex(reader.ReaderError, '^contact_page_count$'):
            self.read()

    def test_query_does_not_modify_vault_and_errors_have_no_source_values(self):
        self.store(page([{'id_contact': 10, 'password': 'SYNTHETIC_PASSWORD'}, {'id_contact': 11}]))
        before = self.database.read_bytes()
        self.read()
        self.assertEqual(before, self.database.read_bytes())
        self.mutate('UPDATE records SET payload_encrypted=?', (b'SYNTHETIC_PASSWORD',))
        with self.assertRaises(reader.ReaderError) as caught:
            self.read()
        self.assertNotIn('SYNTHETIC_PASSWORD', str(caught.exception))


if __name__ == '__main__':
    unittest.main()

"""Synthetic completed-resource proofs; no real source data or network calls."""
import base64
from contextlib import closing
import hashlib
import json
from pathlib import Path
import sqlite3
import unittest
from unittest.mock import patch
import uuid
import zlib

from cryptography.fernet import Fernet

import server_contact_reader as reader


SNAPSHOT = 'a' * 32
STAMP = '2026-11-17T00:00:00+00:00'


class ServerContactReaderTests(unittest.TestCase):
    def setUp(self):
        self.job = Path(__file__).resolve().parents[3] / 'exports' / ('.synthetic-server-reader-' + uuid.uuid4().hex)
        self.job.mkdir()
        self.cipher = Fernet(Fernet.generate_key())
        self.account = 'mastervision'

    def tearDown(self):
        for name in ('snapshot.sqlite', 'contacts.sqlite'):
            for suffix in ('', '-journal', '-wal', '-shm'):
                (self.job / (name + suffix)).unlink(missing_ok=True)
        self.job.rmdir()

    def encrypted(self, raw, page, *, account=None, snapshot=SNAPSHOT):
        profile = reader.PROFILES[account or self.account]
        digest = hashlib.sha256(raw).hexdigest()
        envelope = {'format': profile.page_format, 'account': profile.account,
            'source': profile.api_origin, 'resource': 'contacts', 'page': page,
            'snapshot': snapshot, 'sha256': digest, 'body': base64.b64encode(raw).decode()}
        packed = zlib.compress(json.dumps(envelope).encode())
        storage = {'format': 'avo-server-private-storage-v1', 'account': profile.account,
            'namespace': profile.crypto_namespace, 'source_id': reader._page_key(profile, page),
            'data_b64': base64.b64encode(packed).decode()}
        return digest, self.cipher.encrypt(json.dumps(storage).encode())

    def build(self, pages=None, *, account='mastervision', ids=None, terminal=None):
        self.account = account
        profile = reader.PROFILES[account]
        pages = pages if pages is not None else [[{'id_contact': 10}, {'id_contact': '20'}]]
        ids = ids if ids is not None else sorted(int(row['id_contact']) for rows in pages for row in rows)
        with closing(sqlite3.connect(self.job / 'snapshot.sqlite')) as db:
            db.executescript('''CREATE TABLE metadata(key TEXT PRIMARY KEY,value TEXT);
                CREATE TABLE pages(version_id INTEGER PRIMARY KEY,module TEXT,account TEXT,source TEXT,
                    resource TEXT,page INTEGER,sha256 TEXT,row_count INTEGER,captured_at TEXT,
                    parse_code TEXT,raw_encrypted BLOB);
                CREATE INDEX accepted_page ON pages(resource,page,parse_code);
                CREATE TABLE resource_state(resource TEXT PRIMARY KEY,next_page INTEGER,row_count INTEGER,status TEXT,error_code TEXT);
                CREATE TABLE row_ids(resource TEXT,source_id INTEGER,PRIMARY KEY(resource,source_id));''')
            with db:
                db.executemany('INSERT INTO metadata VALUES (?,?)',
                    {'format': profile.page_format, 'account': account, 'source': profile.api_origin,
                     'page_size': '100', 'snapshot': SNAPSHOT}.items())
                db.execute('INSERT INTO resource_state VALUES (?,?,?,?,?)',
                           ('contacts', len(pages), sum(map(len, pages)), 'complete', None))
                db.execute('INSERT INTO resource_state VALUES (?,?,?,?,?)', ('employee', 0, 0, 'collecting', None))
                db.executemany('INSERT INTO row_ids VALUES (?,?)', [('contacts', ident) for ident in ids])
                for page, rows in enumerate(pages):
                    raw = json.dumps(rows).encode()
                    digest, cipher = self.encrypted(raw, page)
                    db.execute('INSERT INTO pages VALUES (?,?,?,?,?,?,?,?,?,?,?)',
                        (page + 1, profile.page_format, account, profile.api_origin, 'contacts',
                         page, digest, len(rows), STAMP, 'accepted', cipher))
                terminal = terminal if terminal is not None else b'No items where found for model <b>contacts</b>'
                digest, cipher = self.encrypted(terminal, len(pages))
                db.execute('INSERT INTO pages VALUES (?,?,?,?,?,?,?,?,?,?,?)',
                    (len(pages) + 1, profile.page_format, account, profile.api_origin, 'contacts',
                     len(pages), digest, 0, STAMP, 'complete', cipher))
        with closing(sqlite3.connect(self.job / 'contacts.sqlite')) as db:
            db.execute('CREATE TABLE contacts(id INTEGER PRIMARY KEY,record_json TEXT)')
            with db:
                db.executemany('INSERT INTO contacts VALUES (?,?)', [(ident, json.dumps({
                    'source': profile.api_origin, 'contact': {'id': ident}})) for ident in ids])

    def mutate(self, sql, args=(), *, index=False):
        with closing(sqlite3.connect(self.job / ('contacts.sqlite' if index else 'snapshot.sqlite'))) as db:
            with db:
                db.execute(sql, args)

    def read(self, *, account=None, cipher=None):
        return list(reader.iter_contacts(self.job, cipher or self.cipher, account or self.account))

    def test_preserves_profile_and_password_data_but_removes_untrusted_list_link(self):
        self.build([[{'id_contact': 10, 'name': 'Synthetic', 'password': '  SYNTHETIC_PASSWORD  ',
                      'extra': [None, 1], 'link_personal_auth': 'SYNTHETIC_UNTRUSTED'}, {'id_contact': '20'}]])
        self.assertEqual(self.read(), [{'id_contact': '10', 'name': 'Synthetic',
            'password': '  SYNTHETIC_PASSWORD  ', 'extra': [None, 1]}, {'id_contact': '20'}])

    def test_iomp_uses_its_own_identity_and_site_cipher(self):
        self.build(account='iomp')
        self.assertEqual([row['id_contact'] for row in self.read()], ['10', '20'])
        with self.assertRaisesRegex(reader.ContactReadError, '^source_identity_mismatch$'):
            self.read(account='mastervision')
        with self.assertRaisesRegex(reader.ContactReadError, '^wrong_account$'):
            self.read(account='mv-centr')

    def test_rejects_incomplete_contact_resource_even_if_some_pages_exist(self):
        self.build()
        self.mutate("UPDATE resource_state SET status='collecting' WHERE resource='contacts'")
        with self.assertRaisesRegex(reader.ContactReadError, '^contacts_not_complete$'):
            self.read()

    def test_saved_terminal_marker_is_required_and_bound_to_contacts(self):
        self.build(terminal=b'No items where found for model <b>employee</b>')
        with self.assertRaisesRegex(reader.ContactReadError, '^invalid_terminal_marker$'):
            self.read()
        self.mutate("DELETE FROM pages WHERE parse_code='complete'")
        with self.assertRaisesRegex(reader.ContactReadError, '^terminal_marker_missing$'):
            self.read()

    def test_unrelated_html_cannot_prove_completion(self):
        self.build(terminal=b'<html>Please log in</html>')
        with self.assertRaises(reader.ContactReadError):
            self.read()

    def test_reclassified_exact_terminal_marker_is_supported(self):
        self.build()
        self.mutate("UPDATE pages SET parse_code='invalid_json' WHERE parse_code='complete'")
        self.assertEqual(len(self.read()), 2)

    def test_accepted_pages_must_be_unique_and_contiguous(self):
        self.build([[{'id_contact': 10}], [{'id_contact': 20}]])
        self.mutate("UPDATE pages SET page=3 WHERE page=1 AND parse_code='accepted'")
        with self.assertRaisesRegex(reader.ContactReadError, '^incomplete_contact_pages$'):
            self.read()

    def test_saved_id_index_and_snapshot_row_ids_must_match_exactly(self):
        self.build()
        profile = reader.PROFILES[self.account]
        self.mutate('UPDATE contacts SET id=?,record_json=? WHERE id=20',
                    (99, json.dumps({'source': profile.api_origin, 'contact': {'id': 99}})), index=True)
        with self.assertRaisesRegex(reader.ContactReadError, '^source_index_mismatch$'):
            self.read()

    def test_even_extra_invalid_zero_index_rows_are_rejected(self):
        self.build()
        self.mutate('INSERT INTO contacts VALUES (?,?)', (0, '{}'), index=True)
        with self.assertRaisesRegex(reader.ContactReadError, '^source_index_mismatch$'):
            self.read()

    def test_raw_page_ids_must_match_both_indexes_fingerprint(self):
        self.build(ids=[10, 99])
        with self.assertRaisesRegex(reader.ContactReadError, '^source_fingerprint_mismatch$'):
            self.read()

    def test_duplicate_ids_across_pages_are_rejected(self):
        self.build([[{'id_contact': 10}], [{'id_contact': 10}]], ids=[10, 20])
        with self.assertRaisesRegex(reader.ContactReadError, '^source_id_order$'):
            self.read()

    def test_wrong_cipher_and_swapped_page_binding_are_rejected(self):
        self.build()
        with self.assertRaisesRegex(reader.ContactReadError, '^source_crypto_failed$'):
            self.read(cipher=Fernet(Fernet.generate_key()))
        with closing(sqlite3.connect(self.job / 'snapshot.sqlite')) as db:
            terminal = db.execute("SELECT raw_encrypted FROM pages WHERE parse_code='complete'").fetchone()[0]
        self.mutate("UPDATE pages SET raw_encrypted=? WHERE parse_code='accepted'", (terminal,))
        with self.assertRaisesRegex(reader.ContactReadError, '^storage_identity_mismatch$'):
            self.read()

    def test_snapshot_and_raw_hashes_are_bound(self):
        self.build()
        self.mutate("UPDATE pages SET sha256=? WHERE parse_code='accepted'", ('0' * 64,))
        with self.assertRaisesRegex(reader.ContactReadError, '^page_identity_mismatch$'):
            self.read()

    def test_decoder_bounds_compression_before_loading_page_json(self):
        self.build([[{'id_contact': 10, 'text': 'x' * 10000}, {'id_contact': 20}]])
        with patch.object(reader, 'MAX_PAGE_ENVELOPE', 4096), self.assertRaisesRegex(
                reader.ContactReadError, '^payload_too_large$'):
            self.read()

    def test_paused_generator_does_not_block_other_resource_writer(self):
        self.build([[{'id_contact': 10}], [{'id_contact': 20}]])
        iterator = reader.iter_contacts(self.job, self.cipher, self.account)
        self.assertEqual(next(iterator)['id_contact'], '10')
        with closing(sqlite3.connect(self.job / 'snapshot.sqlite', timeout=0.05)) as writer:
            writer.execute("UPDATE resource_state SET row_count=1 WHERE resource='employee'")
            writer.commit()
        self.assertEqual([row['id_contact'] for row in iterator], ['20'])

    def test_reader_does_not_modify_either_source_database(self):
        self.build()
        before = [(self.job / name).read_bytes() for name in ('snapshot.sqlite', 'contacts.sqlite')]
        self.read()
        self.assertEqual(before, [(self.job / name).read_bytes() for name in ('snapshot.sqlite', 'contacts.sqlite')])

    def test_bad_payload_errors_never_echo_source_password(self):
        self.build()
        self.mutate("UPDATE pages SET raw_encrypted=? WHERE parse_code='accepted'", (b'SYNTHETIC_PRIVATE_PASSWORD',))
        with self.assertRaises(reader.ContactReadError) as caught:
            self.read()
        self.assertNotIn('SYNTHETIC_PRIVATE_PASSWORD', str(caught.exception))


if __name__ == '__main__':
    unittest.main()

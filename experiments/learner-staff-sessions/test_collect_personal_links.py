from contextlib import closing
import json
import sqlite3
import unittest

from audit_legacy_links import SHOP_HOST
from collect_personal_links import CollectionError, collect, normalize_detail, parse_key
from private_link_storage import StorageError, protect_url, unprotect_url
from test_audit_legacy_links import row, synthetic_database


def detail(ident):
    return {'id_contact': str(ident), 'password': 'SYNTHETIC_PASSWORD_DISCARD',
            'email': 'synthetic-private@example.invalid',
            'link_personal_auth': f'https://{SHOP_HOST}/personal/auth/secure-login?uid={ident}&vc=SYNTHETIC_TOKEN_{ident}'}


def source_archive(path):
    with closing(sqlite3.connect(path)) as db:
        db.execute('CREATE TABLE contacts (id INTEGER PRIMARY KEY, record_json TEXT)')
        db.executemany('INSERT INTO contacts VALUES (?, ?)', [(i, json.dumps(row(i))) for i in (7, 8, 9)])
        db.commit()


class CollectionTests(unittest.TestCase):
    def test_only_individually_matching_links_are_saved(self):
        with synthetic_database() as source, synthetic_database() as output:
            source_archive(source)
            original = source.read_bytes()
            calls = []

            def fetch(key, ident):
                calls.append(ident)
                self.assertEqual(key, 'SYNTHETIC_KEY')
                return {'data': [detail(ident)]}

            report = collect(source, output, 'SYNTHETIC_KEY', fetch=fetch, pause=lambda _: None)
            self.assertEqual(report['verified'], 3)
            self.assertEqual(report['status'], 'individual_cards_verified')
            self.assertEqual(calls, [7, 8, 9])
            self.assertEqual(source.read_bytes(), original)
            raw = output.read_bytes()
            for secret in (b'SYNTHETIC_PASSWORD_DISCARD', b'synthetic-private@example.invalid', b'SYNTHETIC_KEY',
                           b'SYNTHETIC_TOKEN_'):
                self.assertNotIn(secret, raw)
                self.assertNotIn(secret.decode(), json.dumps(report))
            with closing(sqlite3.connect(output)) as db:
                for ident, encrypted in db.execute('SELECT source_id, url_encrypted FROM links'):
                    self.assertEqual(unprotect_url(ident, encrypted), detail(ident)['link_personal_auth'])

    def test_wrong_uid_stops_before_next_contact(self):
        with synthetic_database() as source, synthetic_database() as output:
            source_archive(source)

            def fetch(key, ident):
                result = detail(ident)
                if ident == 8:
                    result['link_personal_auth'] = detail(7)['link_personal_auth']
                return result

            report = collect(source, output, 'SYNTHETIC_KEY', fetch=fetch, pause=lambda _: None)
            self.assertEqual(report['requested'], 2)
            self.assertEqual(report['verified'], 1)
            self.assertEqual(report['failed'], 1)
            self.assertEqual(report['error_code'], 'detail_url_uid_mismatch')
            with closing(sqlite3.connect(output)) as db:
                self.assertEqual(db.execute('SELECT COUNT(*) FROM links').fetchone()[0], 1)

    def test_existing_output_never_overwritten(self):
        with synthetic_database() as source, synthetic_database() as output:
            source_archive(source)
            output.write_bytes(b'SYNTHETIC_EXISTING_ARCHIVE')
            with self.assertRaisesRegex(CollectionError, '^output_must_be_new$'):
                collect(source, output, 'SYNTHETIC_KEY', fetch=lambda *_: self.fail('network'))
            self.assertEqual(output.read_bytes(), b'SYNTHETIC_EXISTING_ARCHIVE')

    def test_key_input_never_accepts_foreign_api_or_blank(self):
        self.assertEqual(parse_key('SYNTHETIC_KEY'), 'SYNTHETIC_KEY')
        self.assertEqual(parse_key('https://mvcentr.autoweboffice.ru/?r=api/rest/contacts&id=7&key=SYNTHETIC_KEY'),
                         'SYNTHETIC_KEY')
        for value in ('', 'two words', 'https://example.invalid/?key=SYNTHETIC_KEY',
                      'https://mvcentr.autoweboffice.ru/?r=api/rest/accounts&key=SYNTHETIC_KEY'):
            with self.assertRaises(CollectionError):
                parse_key(value)

    def test_wrong_or_ambiguous_detail_denied(self):
        for value in ({'id_contact': '8'}, [detail(7), detail(8)], {'data': [], 'items': [detail(7)]}):
            with self.assertRaises(CollectionError):
                normalize_detail(value, 7)

    def test_exception_text_is_not_copied_to_report(self):
        with synthetic_database() as source, synthetic_database() as output:
            source_archive(source)

            def fetch(*_):
                raise CollectionError('SYNTHETIC_SECRET_DO_NOT_LOG')

            report = collect(source, output, 'SYNTHETIC_KEY', fetch=fetch)
            self.assertEqual(report['error_code'], 'invalid_detail')
            self.assertNotIn('SYNTHETIC_SECRET', json.dumps(report))

    def test_encoded_api_key_cannot_be_saved_in_link(self):
        for encoded in ('%41%42%43', '%252541%252542%252543', '%25252525252525252541'):
            with self.subTest(encoding=encoded), synthetic_database() as source, synthetic_database() as output:
                source_archive(source)

                def fetch(key, ident):
                    response = detail(ident)
                    response['link_personal_auth'] = response['link_personal_auth'].split('&vc=')[0] + '&vc=' + encoded
                    return response

                report = collect(source, output, 'ABC', fetch=fetch)
                self.assertIn(report['error_code'], ('api_key_in_link', 'link_encoding_too_deep'))
                with closing(sqlite3.connect(output)) as db:
                    self.assertEqual(db.execute('SELECT COUNT(*) FROM links').fetchone()[0], 0)

    def test_nonpositive_source_id_is_rejected_before_network(self):
        with synthetic_database() as source, synthetic_database() as output:
            source_archive(source)
            with closing(sqlite3.connect(source)) as db:
                db.execute('UPDATE contacts SET id=0, record_json=? WHERE id=7', (json.dumps(row(0)),))
                db.commit()
            with self.assertRaisesRegex(CollectionError, '^wrong_source_archive$'):
                collect(source, output, 'SYNTHETIC_KEY', fetch=lambda *_: self.fail('network'))
            self.assertFalse(output.exists())

    def test_dpapi_ciphertext_is_bound_to_source_contact(self):
        protected = protect_url(7, detail(7)['link_personal_auth'])
        self.assertEqual(unprotect_url(7, protected), detail(7)['link_personal_auth'])
        with self.assertRaises(StorageError):
            unprotect_url(8, protected)
        with self.assertRaises(StorageError):
            unprotect_url(7, protected[:20])


if __name__ == '__main__':
    unittest.main()

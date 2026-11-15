"""Synthetic archive checks; no real tokens, contact IDs or emails."""
from contextlib import closing, contextmanager, redirect_stdout
import io
import json
from pathlib import Path
import sqlite3
import unittest
import uuid

from audit_legacy_links import API_ORIGIN, SHOP_HOST, audit, inspect_record, main


def row(ident=7, url=None):
    url = url or f'https://{SHOP_HOST}/personal/auth/secure-login?uid={ident}&vc=SYNTHETIC_ONLY'
    return {'source': API_ORIGIN, 'contact': {'id': ident},
            'auth_links': {'user': url, 'api_fields': {'link_personal_auth': url}},
            'api_data': {'list': {'link_personal_auth': url}}}


@contextmanager
def synthetic_database():
    # Existing workspace directory avoids restricted Windows TEMP directory ACLs.
    path = Path(__file__).resolve().parent / ('.synthetic-' + uuid.uuid4().hex + '.sqlite')
    try:
        yield path
    finally:
        for suffix in ('', '-journal', '-wal', '-shm'):
            path.with_name(path.name + suffix).unlink(missing_ok=True)


class LinkAuditTests(unittest.TestCase):
    def test_exact_copies_and_encoded_query(self):
        source = row(url=f'https://{SHOP_HOST}/personal/auth/secure-login?vc=SYNTHETIC%2BONLY&uid=7')
        original = json.dumps(source)
        self.assertEqual(inspect_record(7, source)[0], 'verified')
        self.assertEqual(json.dumps(source), original)

    def test_wrong_account_or_source_id(self):
        source = row()
        source['source'] = 'https://mastervision.autoweboffice.ru'
        self.assertEqual(inspect_record(7, source)[0], 'wrong_source_account')
        self.assertEqual(inspect_record(8, row())[0], 'source_id_mismatch')

    def test_preserved_copy_mismatch(self):
        source = row()
        source['api_data']['list']['link_personal_auth'] = 'SYNTHETIC_DIFFERENT'
        self.assertEqual(inspect_record(7, source)[0], 'source_copy_mismatch')

    def test_unexpected_urls_fail_without_source_values(self):
        base = f'https://{SHOP_HOST}/personal/auth/secure-login'
        urls = [
            'javascript:SYNTHETIC_SECRET',
            f'https://{SHOP_HOST}.example.invalid/personal/auth/secure-login?uid=7&vc=SYNTHETIC_SECRET',
            f'https://staff@{SHOP_HOST}/personal/auth/secure-login?uid=7&vc=SYNTHETIC_SECRET',
            base + '?uid=7&uid=8&vc=SYNTHETIC_SECRET',
            base + '?uid=7&vc=SYNTHETIC_SECRET&staff=1',
            base + '?uid=8&vc=SYNTHETIC_SECRET',
            base + '?uid=7&vc=',
            base + '?uid=7&vc=SYNTHETIC_SECRET#fragment',
            base + '?uid=7&vc=%0D%0A',
            base + '?uid=7&vc=SYNTHETIC_SECRET\n',
        ]
        for url in urls:
            with self.subTest(url_index=urls.index(url)):
                status, private = inspect_record(7, row(url=url))
                self.assertNotEqual(status, 'verified')
                self.assertNotIn('SYNTHETIC_SECRET', status)
                if status != 'url_uid_mismatch':
                    self.assertIsNone(private)

    def test_odd_data_types(self):
        for value in ([], None, 'SYNTHETIC_SECRET', 42):
            self.assertEqual(inspect_record(7, value), ('invalid_record', None))
        for value in ([], {}, 7):
            source = row()
            source['auth_links']['user'] = value
            self.assertEqual(inspect_record(7, source)[0], 'invalid_link_type_or_length')

    def test_read_only_aggregate_report_and_token_collision(self):
        with synthetic_database() as path:
            with closing(sqlite3.connect(path)) as db:
                db.execute('CREATE TABLE contacts (id INTEGER PRIMARY KEY, record_json TEXT)')
                db.executemany('INSERT INTO contacts VALUES (?, ?)',
                               [(7, json.dumps(row(7))), (8, json.dumps(row(8)))])
                db.commit()
            before = path.read_bytes()
            report = audit(path)
            self.assertEqual(path.read_bytes(), before)
            self.assertEqual(report['records_checked'], 2)
            self.assertEqual(report['token_reused_across_contacts'], 1)
            self.assertFalse(report['all_checks_passed'])
            self.assertNotIn('SYNTHETIC_ONLY', json.dumps(report))

    def test_invalid_json_and_missing_file_do_not_leak(self):
        with synthetic_database() as path:
            with closing(sqlite3.connect(path)) as db:
                db.execute('CREATE TABLE contacts (id INTEGER PRIMARY KEY, record_json TEXT)')
                db.execute('INSERT INTO contacts VALUES (7, ?)', ('SYNTHETIC_SECRET',))
                db.commit()
            report = audit(path)
            self.assertEqual(report['status_counts'], {'invalid_json': 1})
            self.assertNotIn('SYNTHETIC_SECRET', json.dumps(report))
            output = io.StringIO()
            with redirect_stdout(output):
                code = main(['--database', str(path.with_name('SYNTHETIC_SECRET.sqlite'))])
            self.assertEqual(code, 2)
            self.assertNotIn('SYNTHETIC_SECRET', output.getvalue())

    def test_page_repeated_link_cannot_be_imported_as_personal(self):
        with synthetic_database() as path:
            with closing(sqlite3.connect(path)) as db:
                db.execute('CREATE TABLE contacts (id INTEGER PRIMARY KEY, record_json TEXT)')
                records = []
                for ident in (7, 8, 9):
                    source = row(7)
                    source['contact']['id'] = ident
                    records.append((ident, json.dumps(source)))
                db.executemany('INSERT INTO contacts VALUES (?, ?)', records)
                db.commit()
            report = audit(path)
            self.assertEqual(report['status_counts'], {'url_uid_mismatch': 2, 'verified': 1})
            self.assertEqual(report['token_reused_across_contacts'], 2)
            self.assertFalse(report['all_checks_passed'])


if __name__ == '__main__':
    unittest.main()

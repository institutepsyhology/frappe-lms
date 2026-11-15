"""Synthetic sender checks: ACK-before-prune, safe retries and live-reader resume."""
from contextlib import closing
import base64
import json
from pathlib import Path
import sqlite3
import unittest
from unittest.mock import patch

import stream_archive_to_frappe as sender
import collect_personal_links_bulk as bulk
from private_link_storage import protect_url, unprotect_url, StorageError
from test_collect_personal_links_bulk import output_directory, source_archive, detail, run

SNAPSHOT = 'a' * 32


def acknowledgement(request):
    return {'format': sender.FORMAT, 'site': sender.SITE, 'snapshot': request['snapshot'],
            'kind': request['kind'], 'records': [{key: row[key] for key in
            ('version_id', 'source_id', 'sha256')} for row in request['records']],
            'stored_total': len(request['records'])}


class SenderTests(unittest.TestCase):
    def fixture(self, folder):
        source = folder / 'source.sqlite'
        source_archive(source, 3)
        destination = folder / 'output'
        run(source, destination)
        return source, destination

    def cleanup_fixture(self, folder):
        for child in folder.iterdir():
            if child.is_dir():
                for path in child.iterdir(): path.unlink()
                child.rmdir()
            else: child.unlink()

    def test_exact_ack_prunes_ciphertext_preserves_fk_and_resume(self):
        with output_directory() as folder:
            try:
                source, dest = self.fixture(folder)
                with closing(sender.open_links(dest / 'links.sqlite', SNAPSHOT)) as db:
                    request = sender.link_batch(db, SNAPSHOT)
                    sender.ack_links(db, request, acknowledgement(request))
                    self.assertEqual(db.execute('SELECT COUNT(*) FROM delivery_receipts').fetchone()[0], 3)
                    self.assertIsNone(sender.link_batch(db, SNAPSHOT))
                    self.assertEqual(db.execute('PRAGMA foreign_key_check').fetchall(), [])
                    encrypted = db.execute('SELECT url_encrypted FROM links LIMIT 1').fetchone()[0]
                    self.assertTrue(encrypted.startswith(sender.REMOTE_PREFIX))
                    with self.assertRaises(StorageError): unprotect_url(1, encrypted)
                report = run(source, dest, fetch=lambda *a: self.fail('Must skip already saved source'))
                self.assertEqual(report['skipped'], 3)
            finally: self.cleanup_fixture(folder)

    def test_bad_ack_never_prunes_or_records_delivery(self):
        with output_directory() as folder:
            try:
                source, dest = self.fixture(folder)
                with closing(sender.open_links(dest / 'links.sqlite', SNAPSHOT)) as db:
                    request = sender.link_batch(db, SNAPSHOT)
                    for patch in ({'site': 'my-lk.iomp.ru'}, {'snapshot': 'b'*32},
                                  {'records': []}, {'kind': 'pages'}, {'stored_total': 0}):
                        ack = dict(acknowledgement(request), **patch)
                        with self.assertRaises(sender.DeliveryError): sender.ack_links(db, request, ack)
                    self.assertEqual(db.execute('SELECT COUNT(*) FROM delivery_receipts').fetchone()[0], 0)
                    self.assertEqual(unprotect_url(1, db.execute('SELECT url_encrypted FROM links WHERE source_id=1').fetchone()[0]), detail(1)['link_personal_auth'])
            finally: self.cleanup_fixture(folder)

    def test_lost_remote_ack_retries_same_payload(self):
        with output_directory() as folder:
            try:
                source, dest = self.fixture(folder)
                with closing(sender.open_links(dest / 'links.sqlite', SNAPSHOT)) as db:
                    first = sender.link_batch(db, SNAPSHOT)
                    self.assertEqual(first, sender.link_batch(db, SNAPSHOT))
                    sender.ack_links(db, first, acknowledgement(first))
                    sender.ack_links(db, first, acknowledgement(first))
                    self.assertEqual(db.execute('SELECT COUNT(*) FROM delivery_receipts').fetchone()[0], 3)
            finally: self.cleanup_fixture(folder)

    def test_remote_reference_without_receipt_is_rejected(self):
        with output_directory() as folder:
            try:
                source, dest = self.fixture(folder)
                with closing(sender.open_links(dest / 'links.sqlite', SNAPSHOT)) as db:
                    req = sender.link_batch(db, SNAPSHOT)
                    sender.ack_links(db, req, acknowledgement(req))
                    with db: db.execute('DELETE FROM delivery_receipts WHERE version_id=1')
                    with self.assertRaises(sender.DeliveryError): sender.link_batch(db, SNAPSHOT)
                with self.assertRaises(bulk.BulkError): bulk.open_output(dest / 'links.sqlite', bulk.validate_source(source,'mv-centr')[1],3)
            finally: self.cleanup_fixture(folder)

    def test_another_producer_commit_is_visible_after_ack(self):
        with output_directory() as folder:
            try:
                source, dest = self.fixture(folder)
                with closing(sender.open_links(dest / 'links.sqlite', SNAPSHOT)) as db:
                    request = sender.link_batch(db, SNAPSHOT)
                    with closing(sqlite3.connect(dest / 'links.sqlite')) as producer:
                        url = detail(1,'SYNTHETIC_UPDATED')['link_personal_auth']
                        _, digest = bulk.verified_link(1,detail(1,'SYNTHETIC_UPDATED'))
                        bulk.append_verified(producer,1,protect_url(1,url),digest,'2026-11-16T00:00:00+00:00','individual_detail')
                    sender.ack_links(db, request, acknowledgement(request))
                    next_batch = sender.link_batch(db, SNAPSHOT)
                    self.assertEqual(len(next_batch['records']),1)
                    self.assertEqual(next_batch['records'][0]['version_id'],4)
            finally: self.cleanup_fixture(folder)

    def test_invalid_local_ciphertext_or_digest_never_leaves_client(self):
        with output_directory() as folder:
            try:
                source, dest = self.fixture(folder)
                with closing(sender.open_links(dest / 'links.sqlite', SNAPSHOT)) as db:
                    with db: db.execute("UPDATE links SET token_digest=x'0000' WHERE version_id=1")
                    with self.assertRaises(sender.DeliveryError): sender.link_batch(db,SNAPSHOT)
            finally: self.cleanup_fixture(folder)

    def test_failed_local_batch_rolls_back_every_prune(self):
        with output_directory() as folder:
            try:
                source, dest = self.fixture(folder)
                with closing(sender.open_links(dest / 'links.sqlite', SNAPSHOT)) as db:
                    request=sender.link_batch(db,SNAPSHOT)
                    with db: db.execute('UPDATE links SET url_encrypted=? WHERE version_id=2',
                        (protect_url(2,detail(2,'SYNTHETIC_CHANGED')['link_personal_auth']),))
                    with self.assertRaises(sender.DeliveryError): sender.ack_links(db,request,acknowledgement(request))
                    self.assertEqual(db.execute('SELECT COUNT(*) FROM delivery_receipts').fetchone()[0],0)
                    self.assertEqual(unprotect_url(1,db.execute('SELECT url_encrypted FROM links WHERE version_id=1').fetchone()[0]),detail(1)['link_personal_auth'])
            finally: self.cleanup_fixture(folder)

    def test_shared_database_allows_parallel_producer_and_sender(self):
        import threading
        with output_directory() as folder:
            try:
                source,dest=self.fixture(folder)
                errors=[]
                def produce():
                    try:
                        with closing(sqlite3.connect(dest/'links.sqlite',timeout=5)) as producer:
                            for n in range(20):
                                value=detail(1,'SYNTHETIC_NEXT_'+str(n))
                                _,digest=bulk.verified_link(1,value)
                                bulk.append_verified(producer,1,protect_url(1,value['link_personal_auth']),digest,
                                    '2026-11-16T00:00:00+00:00','individual_detail')
                    except BaseException as error: errors.append(type(error).__name__)
                thread=threading.Thread(target=produce)
                thread.start()
                with closing(sender.open_links(dest/'links.sqlite',SNAPSHOT)) as db:
                    while thread.is_alive() or sender.link_batch(db,SNAPSHOT):
                        req=sender.link_batch(db,SNAPSHOT)
                        if req: sender.ack_links(db,req,acknowledgement(req))
                    thread.join()
                    self.assertEqual(errors,[])
                    self.assertEqual(db.execute('SELECT COUNT(*) FROM delivery_receipts').fetchone()[0],23)
                    self.assertEqual(db.execute('PRAGMA foreign_key_check').fetchall(),[])
            finally: self.cleanup_fixture(folder)

    def test_ssh_payload_uses_stdin_and_fixed_verified_destination(self):
        args = sender.ssh_arguments('SYNTHETIC_PROGRAM')
        self.assertIn('StrictHostKeyChecking=yes',args)
        self.assertIn('BatchMode=yes',args)
        self.assertIn('root@89.223.71.30',args)
        self.assertIn('my-lk.mv-centr.ru',sender.SITE)
        self.assertNotIn('SYNTHETIC_TOKEN',repr(args))

    def test_ten_transfer_failures_stop_source_without_losing_payload(self):
        with output_directory() as folder:
            try:
                source,dest=self.fixture(folder)
                delivery=folder/'delivery';delivery.mkdir()
                calls=[]
                def fail(request):
                    calls.append(1)
                    raise sender.DeliveryError('remote_result_uncertain')
                with patch.object(sender,'directories',return_value=(folder,dest,delivery,SNAPSHOT)):
                    result=sender.run(folder,transport=fail,pause=lambda _:None)
                self.assertEqual(result['status'],'stopped')
                self.assertEqual(result['consecutive_failures'],10)
                self.assertEqual(len(calls),10)
                self.assertTrue((folder/'STOP').is_file())
                with closing(sqlite3.connect(dest/'links.sqlite')) as db:
                    self.assertEqual(db.execute('SELECT COUNT(*) FROM delivery_receipts').fetchone()[0],0)
                    self.assertEqual(unprotect_url(1,db.execute('SELECT url_encrypted FROM links WHERE version_id=1').fetchone()[0]),detail(1)['link_personal_auth'])
            finally:self.cleanup_fixture(folder)

    def test_critical_disk_space_halts_reader_before_any_transfer(self):
        from types import SimpleNamespace
        with output_directory() as folder:
            try:
                source,dest=self.fixture(folder)
                delivery=folder/'delivery';delivery.mkdir()
                with patch.object(sender,'directories',return_value=(folder,dest,delivery,SNAPSHOT)), \
                        patch.object(sender.shutil,'disk_usage',return_value=SimpleNamespace(free=1)):
                    result=sender.run(folder,transport=lambda _:self.fail('No transfer on full disk'))
                self.assertEqual(result['error_code'],'local_space_critical')
                self.assertTrue((folder/'STOP').is_file())
            finally:self.cleanup_fixture(folder)

    def test_real_synthetic_page_and_link_pipeline(self):
        import legacy_api_snapshot as raw_archive
        import server_archive_sink as sink
        from cryptography.fernet import Fernet
        with output_directory() as folder:
            try:
                with closing(raw_archive.open_archive(folder/'snapshot.sqlite',100)) as db:
                    snapshot=dict(db.execute('SELECT key,value FROM metadata'))['snapshot']
                    body=b'[{"id_contact":1}]'
                    import hashlib
                    with db: db.execute('INSERT INTO pages VALUES (NULL,?,?,?,?,?,?,?,?,?,?)',
                        (raw_archive.FORMAT,'mv-centr',sender.API_ORIGIN,'contacts',0,
                         hashlib.sha256(body).hexdigest(),1,'2026-11-16T00:00:00+00:00','accepted',
                         raw_archive.protect_page('contacts',0,body,snapshot)))
                source_archive(folder/'contacts.sqlite',3)
                run(folder/'contacts.sqlite',folder/('links-'+snapshot))
                cipher=Fernet(Fernet.generate_key())
                def transport(request):
                    return sink.handle_request(request,root=folder/'remote',cipher=cipher)
                result=sender.run(folder,once=True,transport=transport)
                self.assertEqual(result['links_delivered'],3)
                self.assertEqual(result['pages_delivered'],1)
                self.assertEqual(result['pending_links'],0)
                result2=sender.run(folder,once=True,transport=transport)
                self.assertEqual(result2['consecutive_failures'],0)
                with closing(sqlite3.connect(folder/'remote/archive.sqlite')) as db:
                    self.assertEqual(db.execute('SELECT COUNT(*) FROM records').fetchone()[0],4)
            finally: self.cleanup_fixture(folder)


if __name__ == '__main__': unittest.main()

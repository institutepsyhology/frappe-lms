import os
import threading
import time
import unittest
from unittest.mock import patch

import progress_io
from test_collect_personal_links_bulk import output_directory


class ProgressIOTests(unittest.TestCase):
    def test_atomic_roundtrip_and_bounded_reader(self):
        with output_directory() as folder:
            path = folder / 'progress.json'
            progress_io.write_json(path, {'status': 'collecting', 'verified_total': 3})
            self.assertEqual(progress_io.read_json(path)['verified_total'], 3)
            with self.assertRaisesRegex(ValueError, '^progress_too_large$'):
                progress_io.read_json(path, max_bytes=2)

    @unittest.skipUnless(os.name == 'nt', 'Windows sharing regression')
    def test_ordinary_reader_lock_is_retried_without_stopping_writer(self):
        with output_directory() as folder:
            path = folder / 'progress.json'
            progress_io.write_json(path, {'status': 'old'})
            locked_reader = path.open('rb')
            retry_seen, release = threading.Event(), threading.Event()
            failures = []

            def pause(_):
                retry_seen.set()
                release.wait(2)

            def writer():
                try:
                    progress_io.write_json(path, {'status': 'new'}, pause=pause)
                except BaseException as error:
                    failures.append(type(error).__name__)

            thread = threading.Thread(target=writer)
            thread.start()
            try:
                self.assertTrue(retry_seen.wait(2))
            finally:
                locked_reader.close()
                release.set()
                thread.join(3)
            self.assertFalse(thread.is_alive())
            self.assertEqual(failures, [])
            self.assertEqual(progress_io.read_json(path)['status'], 'new')

    def test_persistent_lock_is_bounded_and_preserves_old_progress(self):
        with output_directory() as folder:
            path = folder / 'progress.json'
            progress_io.write_json(path, {'status': 'old'})
            error = PermissionError(13, 'SYNTHETIC_PRIVATE_MESSAGE')
            error.winerror = 5
            waits = []
            with patch.object(progress_io.os, 'replace', side_effect=error) as replace:
                with self.assertRaises(progress_io.ProgressWriteError) as caught:
                    progress_io.write_json(path, {'status': 'new'}, attempts=3, pause=waits.append)
            self.assertEqual(replace.call_count, 3)
            self.assertEqual(len(waits), 2)
            self.assertNotIn('SYNTHETIC_PRIVATE_MESSAGE', str(caught.exception))
            self.assertEqual(progress_io.read_json(path), {'status': 'old'})

    def test_repeated_updates_with_concurrent_gui_reads(self):
        with output_directory() as folder:
            path = folder / 'progress.json'
            progress_io.write_json(path, {'verified_total': 0})
            stop = threading.Event()
            failures = []

            def reader():
                while not stop.is_set():
                    try:
                        value = progress_io.read_json(path)
                        if type(value.get('verified_total')) is not int:
                            failures.append('invalid_count')
                    except (OSError, ValueError) as error:
                        failures.append((type(error).__name__, getattr(error, 'errno', None),
                                         getattr(error, 'winerror', None)))
                    time.sleep(0.001)

            thread = threading.Thread(target=reader)
            thread.start()
            try:
                for value in range(1, 501):
                    progress_io.write_json(path, {'verified_total': value})
            finally:
                stop.set()
                thread.join(3)
            self.assertEqual(failures, [])
            self.assertEqual(progress_io.read_json(path)['verified_total'], 500)

    def test_disk_full_is_not_hidden_or_retried(self):
        with output_directory() as folder:
            path = folder / 'progress.json'
            waits = []
            with patch.object(progress_io.os, 'replace', side_effect=OSError(28, 'disk full')):
                with self.assertRaises(OSError):
                    progress_io.write_json(path, {'status': 'new'}, pause=waits.append)
            self.assertEqual(waits, [])


if __name__ == '__main__':
    unittest.main()

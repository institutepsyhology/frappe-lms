"""Synthetic streamed MP3/filesystem checks; no real URLs, credentials or DB."""
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import stat
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import urllib.error
import uuid

import server_audio_stage as stage

URL = 'https://f1.autoweboffice.ru/synthetic/audio.mp3'


def mp3(size=150000):
    return b'ID3\x04\x00\x00\x00\x00\x00\x00\xff\xfb\x90\x00' + b'a' * (size - 14)


class Response:
    def __init__(self, body=None, **changes):
        self.body = mp3() if body is None else body
        self.status, self.url = 200, URL
        self.headers = {'Content-Length': str(len(self.body)), 'Content-Type': 'audio/mpeg'}
        self.position, self.reads, self.interrupt_after = 0, [], None
        for key, value in changes.items(): setattr(self, key, value)
    def __enter__(self): return self
    def __exit__(self, *_): return False
    def geturl(self): return self.url
    def read(self, size):
        self.reads.append(size)
        if self.interrupt_after is not None and self.position >= self.interrupt_after:
            raise urllib.error.URLError('synthetic interruption with PRIVATE source')
        result = self.body[self.position:self.position + size]
        self.position += len(result)
        return result


class Opener:
    def __init__(self): self.calls, self.response, self.error = [], Response(), None
    def open(self, request, timeout):
        self.calls.append((request, timeout))
        if self.error: raise self.error
        return self.response


class StageTests(unittest.TestCase):
    def setUp(self):
        self.parent = Path(__file__).resolve().parents[3] / '.tmp-mastervision-audio-stage-tests'
        self.parent.mkdir(exist_ok=True)
        self.folder = self.parent / ('fixture-' + uuid.uuid4().hex); self.folder.mkdir()
        self.root = self.folder / stage.SITE / 'private/files'; self.root.mkdir(parents=True)
        self.addCleanup(self.cleanup)
        self.opener = Opener()
        self.builder = patch.object(stage.urllib.request, 'build_opener', return_value=self.opener)
        self.mock_builder = self.builder.start(); self.addCleanup(self.builder.stop)

    def cleanup(self):
        if self.folder.parent.resolve() != self.parent.resolve() or not self.folder.name.startswith('fixture-'):
            raise RuntimeError('unsafe_fixture_cleanup')
        shutil.rmtree(self.folder)

    def run_stage(self, size=150000): return stage.stage_one(URL, size, self.root)

    def paths(self):
        name = stage.PREFIX + hashlib.sha256(URL.encode()).hexdigest() + '.mp3'
        return self.root / name, self.root / (name + '.part'), self.root / (name + '.json')

    def test_streams_in_64k_chunks_with_exact_hashes_private_receipt_and_no_auth(self):
        result = self.run_stage(); final, part, receipt = self.paths()
        self.assertEqual(result['code'], 'audio_staged')
        self.assertEqual(final.read_bytes(), mp3()); self.assertFalse(part.exists())
        self.assertEqual(result['sha256'], hashlib.sha256(mp3()).hexdigest())
        self.assertEqual(result['md5'], hashlib.md5(mp3(), usedforsecurity=False).hexdigest())
        self.assertEqual(json.loads(receipt.read_text()), {k: v for k, v in result.items() if k != 'code'})
        self.assertTrue(all(size == 65536 for size in self.opener.response.reads))
        request, timeout = self.opener.calls[0]
        self.assertEqual(timeout, 30); self.assertEqual(request.get_method(), 'GET'); self.assertIsNone(request.data)
        self.assertFalse({'cookie', 'authorization'} & {name.lower() for name in request.headers})
        self.assertEqual(self.opener.addheaders, [])
        self.assertEqual(self.mock_builder.call_args.args[0].proxies, {})
        self.assertIsInstance(self.mock_builder.call_args.args[1], stage.NoRedirect)
        self.assertIsNone(stage.NoRedirect().redirect_request(None, None, 302, '', {}, URL))
        self.assertNotIn(URL, json.dumps(result)); self.assertNotIn(str(self.root), json.dumps(result))

    def test_repeat_rehashes_existing_bytes_without_network_or_second_file(self):
        first = self.run_stage(); self.opener.calls.clear()
        second = self.run_stage()
        self.assertEqual(second['code'], 'audio_reused')
        self.assertEqual(second['sha256'], first['sha256']); self.assertEqual(self.opener.calls, [])
        self.assertEqual(len(list(self.root.glob('*.mp3'))), 1)

    def test_interrupted_read_never_publishes_partial_or_leaves_its_part(self):
        self.opener.response.interrupt_after = 65536
        with self.assertRaisesRegex(stage.StageError, '^audio_download_or_io_failed$'):
            self.run_stage()
        self.assertEqual(list(self.root.iterdir()), [])
        self.opener.response = Response()
        self.assertEqual(self.run_stage()['code'], 'audio_staged')

    def test_short_and_oversized_bodies_leave_no_final_or_receipt(self):
        for body in (mp3(150000)[:-1], mp3(150001)):
            self.opener.response = Response(body, headers={'Content-Length': '150000', 'Content-Type': 'audio/mpeg'})
            with self.subTest(size=len(body)), self.assertRaisesRegex(stage.StageError, '^audio_body_size_invalid$'):
                self.run_stage()
            self.assertEqual(list(self.root.iterdir()), [])

    def test_size_cap_expected_type_and_free_space_are_checked_before_network(self):
        for size in (True, 0, 9, '150000', stage.MAX_SIZE + 1):
            with self.subTest(size=size), self.assertRaisesRegex(stage.StageError, 'expected_size_invalid'):
                self.run_stage(size)
        with patch.object(stage.shutil, 'disk_usage', return_value=SimpleNamespace(free=100)):
            with self.assertRaisesRegex(stage.StageError, 'space_low'): self.run_stage()
        self.assertEqual(self.opener.calls, []); self.assertEqual(list(self.root.iterdir()), [])

    def test_redirect_non200_missing_length_and_wrong_type_never_write(self):
        failures = [Response(url='https://f2.autoweboffice.com/other.mp3'), Response(status=206),
                    Response(headers={'Content-Type': 'audio/mpeg'}),
                    Response(headers={'Content-Length': '149999', 'Content-Type': 'audio/mpeg'}),
                    Response(headers={'Content-Length': '150000', 'Content-Type': 'text/html'})]
        for response in failures:
            self.opener.response = response
            with self.assertRaises(stage.StageError): self.run_stage()
            self.assertEqual(response.reads, []); self.assertEqual(list(self.root.iterdir()), [])
        self.opener.error = urllib.error.HTTPError(URL, 302, 'PRIVATE source redirect', {}, None)
        with self.assertRaisesRegex(stage.StageError, '^audio_redirect_forbidden$'): self.run_stage()
        self.assertEqual(list(self.root.iterdir()), [])

    def test_valid_mpeg_header_allowed_but_html_jpeg_and_invalid_headers_rejected(self):
        self.assertTrue(stage._magic(b'\xff\xfb\x90\x00', 100))
        self.assertTrue(stage._magic(mp3()[:10], 150000))
        for head in (b'<html>Login', b'\xff\xd8\xffJPEG', b'ID3\x01\x00\x00\x00\x00\x00\x00',
                     b'ID3\x04\x00\x01\x00\x00\x00\x00',
                     b'ID3\x04\x00\x00\x7f\x7f\x7f\x7f', b'\xff\xeb\x90\x00', b'\xff\xfb\xf0\x00'):
            self.assertFalse(stage._magic(head, 150000))
        self.opener.response = Response(b'<html>' + b'a' * 149994)
        with self.assertRaisesRegex(stage.StageError, 'audio_magic_invalid'): self.run_stage()
        self.assertEqual(list(self.root.iterdir()), [])

    def test_existing_mismatched_hash_receipt_or_unknown_partial_is_never_overwritten(self):
        self.run_stage(); final, part, receipt = self.paths(); before = receipt.read_bytes()
        changed = bytearray(final.read_bytes()); changed[-1] ^= 1; final.write_bytes(changed)
        self.opener.calls.clear()
        with self.assertRaisesRegex(stage.StageError, 'existing_hash_mismatch'): self.run_stage()
        self.assertEqual(final.read_bytes(), changed); self.assertEqual(receipt.read_bytes(), before)
        self.assertEqual(self.opener.calls, [])
        final.unlink(); receipt.unlink(); part.write_bytes(b'unrelated preexisting partial')
        with self.assertRaisesRegex(stage.StageError, 'partial_exists'): self.run_stage()
        self.assertEqual(part.read_bytes(), b'unrelated preexisting partial')

    def test_completed_part_and_receipt_recover_after_interrupted_atomic_rename(self):
        with patch.object(stage.os, 'rename', side_effect=OSError('synthetic crash')):
            with self.assertRaises(stage.StageError): self.run_stage()
        final, part, receipt = self.paths()
        self.assertFalse(final.exists()); self.assertTrue(part.exists()); self.assertTrue(receipt.exists())
        self.opener.calls.clear()
        result = self.run_stage()
        self.assertEqual(result['code'], 'audio_recovered'); self.assertEqual(self.opener.calls, [])
        self.assertEqual(final.read_bytes(), mp3()); self.assertFalse(part.exists())

    def test_wrong_site_root_and_bad_urls_rejected_before_network(self):
        wrong = self.folder / 'my-lk.mv-centr.ru/private/files'; wrong.mkdir(parents=True)
        with self.assertRaisesRegex(stage.StageError, 'root_invalid'): stage.stage_one(URL, 150000, wrong)
        with self.assertRaisesRegex(stage.StageError, 'root_invalid'): stage.stage_one(URL, 150000, None)
        values = ['http://f1.autoweboffice.ru/a.mp3', 'https://f2.autoweboffice.ru/a.mp3',
                  'https://f1.autoweboffice.com.evil.test/a.mp3', 'https://127.0.0.1/a.mp3',
                  'https://u:p@f1.autoweboffice.com/a.mp3', 'https://f1.autoweboffice.com:443/a.mp3',
                  URL+'?secret=test', URL+'#fragment', URL+'?', URL+'#',
                  'https://f1.autoweboffice.ru/a/../b.mp3', 'https://f1.autoweboffice.ru/a/%2e%2e/b.mp3',
                  'https://f1.autoweboffice.ru/a/%252e%252e/b.mp3', 'https://f1.autoweboffice.ru/a/%00b.mp3',
                  'https://f1.autoweboffice.ru/a/%2fb.mp3', 'https://f1.autoweboffice.ru/a/%XXb.mp3',
                  'https://f1.autoweboffice.ru/a/%FFb.mp3', 'https://f1.autoweboffice.ru/a.svg']
        for url in values:
            with self.subTest(url=url), self.assertRaisesRegex(stage.StageError, 'audio_url_invalid'):
                stage.stage_one(url, 150000, self.root)
        self.assertEqual(self.opener.calls, [])
        for url in ('https://f2.autoweboffice.com/a.mp3', 'https://f1.autoweboffice.ru/%D1%82%D0%B5%D1%81%D1%82/a%20b.MP3'):
            self.assertEqual(stage._url(url), url)

    def test_symlink_file_or_root_cannot_target_unrelated_bytes(self):
        outside = self.folder / 'unrelated'; outside.write_bytes(b'unchanged')
        final, _, _ = self.paths()
        try: final.symlink_to(outside)
        except OSError: self.skipTest('symlink creation requires OS permission')
        with self.assertRaisesRegex(stage.StageError, 'path_invalid'): self.run_stage()
        self.assertEqual(outside.read_bytes(), b'unchanged'); self.assertEqual(self.opener.calls, [])

    def test_symlink_fences_also_work_without_os_link_creation_privilege(self):
        with patch.object(stage.Path, 'is_symlink', autospec=True, side_effect=lambda path: path == self.root):
            with self.assertRaisesRegex(stage.StageError, 'root_invalid'): self.run_stage()
        fake = SimpleNamespace(lstat=lambda: SimpleNamespace(st_mode=stat.S_IFLNK | 0o777, st_nlink=1))
        with self.assertRaisesRegex(stage.StageError, 'path_invalid'): stage._regular(fake)
        self.assertEqual(self.opener.calls, [])

    def test_cli_failure_contains_only_fixed_code_not_url_or_exception_details(self):
        value=json.dumps({'url': URL+'?private=value', 'expected_size':150000, 'site_files_root':str(self.root)})
        output=io.StringIO()
        with patch.object(stage.sys, 'argv', ['stage']), patch.object(stage.sys, 'stdin', io.StringIO(value)), \
                patch.object(stage.sys, 'stdout', output):
            self.assertEqual(stage.main(), 1)
        self.assertEqual(json.loads(output.getvalue()), {'code':'audio_url_invalid'})
        self.assertNotIn('private=value', output.getvalue())


if __name__ == '__main__':
    unittest.main()

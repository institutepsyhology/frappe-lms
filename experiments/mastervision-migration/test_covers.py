"""Synthetic course-cover MCP checks; no source data, credentials or uploads."""
import base64
import copy
import hashlib
import struct
import unittest
import zlib

import covers
from importer import Review, Stop


def png(alpha=255):
    def chunk(kind, value):
        return len(value).to_bytes(4, 'big') + kind + value + (zlib.crc32(kind + value) & 0xffffffff).to_bytes(4, 'big')
    return (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', 1, 1, 8, 6, 0, 0, 0)) +
            chunk(b'IDAT', zlib.compress(bytes([0, 0, 0, 0, alpha]))) + chunk(b'IEND', b''))


def file_document(raw, course='target-course', name='owned-file'):
    sha = hashlib.sha256(raw).hexdigest()
    filename = 'avo-mastervision-course-618-' + sha[:16] + '.png'
    return {'doctype': 'File', 'name': name, 'file_name': filename, 'file_url': '/files/' + filename,
            'is_private': 0, 'attached_to_doctype': 'LMS Course', 'attached_to_name': course,
            'attached_to_field': 'image', 'file_size': len(raw),
            'content_hash': hashlib.md5(raw, usedforsecurity=False).hexdigest()}


class Client:
    site, account = 'my-lk.mastervision.su', 'mastervision'

    def __init__(self):
        self.course = {'doctype': 'LMS Course', 'name': 'target-course', 'custom_avo_account': self.account,
            'custom_avo_id': '618', 'custom_lms_id': '618', 'published': 0, 'image': None,
            'modified': '2026-11-12 12:00:00.000000', 'modified_by': 'Administrator',
            'title': 'PRIVATE COURSE TITLE', 'description': '<p>PRIVATE CONTENT</p>',
            'disable_self_learning': 1, 'chapters': [{'chapter': 'chapter-1', 'idx': 1,
            'modified': '2026-11-12 12:00:00.000000', 'modified_by': 'Administrator'}]}
        self.files, self.calls, self.mutations = [], [], []
        self.duplicate = False
        self.missing = False
        self.fail_create = False
        self.fail_update = False
        self.bad_hash = False
        self.change_on_create = False
        self.race_at_update = False
        self.change_content = False
        self.bad_file_readback = False

    def call(self, tool, arguments):
        self.calls.append((tool, copy.deepcopy(arguments)))
        if tool == 'list_documents':
            if arguments['doctype'] == 'LMS Course':
                rows = [] if self.missing else [self.course] * (2 if self.duplicate else 1)
                return {'documents': copy.deepcopy(rows), 'has_next_page': False}
            assert arguments['doctype'] == 'File'
            rows = self.files
            for key, op, value in arguments['filters']:
                assert op in ('=', 'like')
                rows = [row for row in rows if row.get(key) == value] if op == '=' else [row for row in rows if row.get(key, '').startswith(value[:-1])]
            return {'documents': copy.deepcopy(rows), 'has_next_page': False}
        assert tool == 'get_document'
        if arguments['doctype'] == 'LMS Course': return copy.deepcopy(self.course)
        assert arguments['doctype'] == 'File'
        row = next(row for row in self.files if row['name'] == arguments['name'])
        value = copy.deepcopy(row)
        if self.bad_file_readback: value['attached_to_name'] = 'another-course'
        return value

    def rpc(self, method, params):
        assert method == 'tools/call'
        tool, arguments = params['name'], params['arguments']
        self.mutations.append((tool, copy.deepcopy(arguments)))
        if tool == 'create_document':
            assert arguments['doctype'] == 'File'
            data = arguments['data']
            assert set(data) == {'file_name', 'content', 'decode', 'is_private', 'attached_to_doctype', 'attached_to_name', 'attached_to_field'}
            assert data['decode'] == 1 and data['is_private'] == 0
            assert (data['attached_to_doctype'], data['attached_to_name'], data['attached_to_field']) == ('LMS Course', self.course['name'], 'image')
            raw = base64.b64decode(data['content'], validate=True)
            file = file_document(raw, name='new-file-' + str(len(self.files) + 1))
            assert file['file_name'] == data['file_name']
            if self.bad_hash: file['content_hash'] = '0' * 32
            self.files.append(file)
            if self.change_on_create:
                self.course['image'] = '/files/manual-cover.png'
                self.course['modified'] = '2026-11-12 12:00:01.000000'
            if self.fail_create: raise RuntimeError('PRIVATE AUTH SOURCE RESPONSE after possible commit')
            return {'structuredContent': copy.deepcopy(file)}
        assert tool == 'update_document' and arguments['doctype'] == 'LMS Course'
        assert arguments['name'] == self.course['name']
        assert set(arguments['data']) == {'image', 'modified'}
        if self.race_at_update:
            self.course['image'] = '/files/manual-cover.png'
            self.course['modified'] = '2026-11-12 12:00:01.000000'
        if arguments['data']['modified'] != self.course['modified']:
            return {'isError': True, 'content': [{'text': 'PRIVATE TIMESTAMP CONFLICT'}]}
        self.course['image'] = arguments['data']['image']
        self.course['modified'] = '2026-11-12 12:00:02.000000'
        self.course['chapters'][0]['modified'] = self.course['modified']
        if self.change_content: self.course['description'] = 'Unexpectedly changed'
        if self.fail_update: raise RuntimeError('PRIVATE response after possible commit')
        return {'structuredContent': copy.deepcopy(self.course)}


class CoverTests(unittest.TestCase):
    def test_wrong_site_or_account_never_reads_or_writes(self):
        for attribute, value in [('site', 'my-lk.mv-centr.ru'), ('site', 'my-lk.iomp.ru'), ('account', 'mv-centr')]:
            client = Client(); setattr(client, attribute, value)
            with self.subTest(attribute=attribute, value=value), self.assertRaisesRegex(Stop, 'wrong_frappe_site'):
                covers.sync_cover(client, 618, png(), 'png', apply=True)
            self.assertEqual(client.calls + client.mutations, [])

    def test_missing_duplicate_published_and_mismatched_courses_never_upload(self):
        for field, value in [('missing', True), ('duplicate', True), ('published', 1),
                             ('custom_lms_id', '619'), ('custom_avo_account', 'mv-centr')]:
            client = Client()
            if field in ('missing', 'duplicate'): setattr(client, field, value)
            else: client.course[field] = value
            with self.subTest(field=field), self.assertRaises((Review, Stop)):
                covers.sync_cover(client, 618, png(), 'png', apply=True)
            self.assertEqual(client.mutations, [])

    def test_invalid_raster_extension_and_apply_type_do_not_touch_target(self):
        for raw, extension, apply in [(b'<svg/>', 'png', True), (png(), 'svg', True),
                                      (png(), 'jpg', True), (png(), 'png', 1)]:
            client = Client()
            with self.subTest(extension=extension, apply=apply), self.assertRaises(Review):
                covers.sync_cover(client, 618, raw, extension, apply)
            self.assertEqual(client.calls + client.mutations, [])

    def test_dry_run_resolves_course_without_mutations_or_payload_in_result(self):
        client = Client()
        result = covers.sync_cover(client, '618', png(), 'png')
        self.assertEqual(result['status'], 'ready')
        self.assertEqual(result['course_id'], '618')
        self.assertFalse(result['file_created'])
        self.assertEqual(client.mutations, [])
        self.assertNotIn('PRIVATE', repr(result))
        self.assertNotIn('https://', repr(result))

    def test_apply_creates_attached_public_file_and_only_changes_course_image(self):
        client = Client(); before = covers._content(client.course)
        result = covers.sync_cover(client, 618, png(), 'png', apply=True)
        self.assertEqual(result['status'], 'created')
        self.assertTrue(result['file_created'])
        self.assertEqual([tool for tool, _ in client.mutations], ['create_document', 'update_document'])
        self.assertEqual(client.files[0]['file_name'], 'avo-mastervision-course-618-' + hashlib.sha256(png()).hexdigest()[:16] + '.png')
        self.assertEqual(client.course['image'], client.files[0]['file_url'])
        self.assertEqual(covers._content(client.course), before)
        self.assertEqual(client.mutations[1][1]['data']['modified'], '2026-11-12 12:00:00.000000')

    def test_repeat_is_idempotent_without_a_second_file_or_update(self):
        client = Client()
        covers.sync_cover(client, 618, png(), 'png', apply=True)
        client.mutations.clear()
        result = covers.sync_cover(client, 618, png(), 'png', apply=True)
        self.assertEqual(result['status'], 'already_imported')
        self.assertEqual(len(client.files), 1)
        self.assertEqual(client.mutations, [])

    def test_preexisting_owned_file_is_reused_after_interrupted_course_update(self):
        client = Client(); client.files = [file_document(png())]
        result = covers.sync_cover(client, 618, png(), 'png', apply=True)
        self.assertEqual(result['status'], 'updated')
        self.assertFalse(result['file_created'])
        self.assertEqual([tool for tool, _ in client.mutations], ['update_document'])

    def test_manual_or_other_course_cover_is_preserved(self):
        for url, existing in [('https://images.example.test/manual.png', None), ('/files/manual.png', None),
                              (file_document(png())['file_url'], file_document(png(), course='other-course'))]:
            client = Client(); client.course['image'] = url
            if existing: client.files.append(existing)
            result = covers.sync_cover(client, 618, png(), 'png', apply=True)
            self.assertEqual(result['status'], 'skipped_existing_cover')
            self.assertEqual(client.course['image'], url)
            self.assertEqual(client.mutations, [])

    def test_new_source_cover_replaces_only_a_proven_owned_cover(self):
        client = Client(); old = file_document(png(alpha=127)); client.files = [old]
        client.course['image'] = old['file_url']
        result = covers.sync_cover(client, 618, png(), 'png', apply=True)
        self.assertEqual(result['status'], 'created')
        self.assertEqual(len(client.files), 2)  # Old file remains; never delete.
        self.assertEqual(client.course['image'], client.files[1]['file_url'])

    def test_uncertain_create_stops_without_retry_update_or_deletion(self):
        client = Client(); client.fail_create = True
        with self.assertRaisesRegex(Stop, '^cover_write_uncertain$'):
            covers.sync_cover(client, 618, png(), 'png', apply=True)
        self.assertEqual(len(client.files), 1)
        self.assertIsNone(client.course['image'])
        self.assertEqual([tool for tool, _ in client.mutations], ['create_document'])

    def test_uncertain_update_stops_and_preserves_file_without_cleanup(self):
        client = Client(); client.fail_update = True
        with self.assertRaisesRegex(Stop, '^cover_write_uncertain$'):
            covers.sync_cover(client, 618, png(), 'png', apply=True)
        self.assertEqual(len(client.files), 1)
        self.assertEqual([tool for tool, _ in client.mutations], ['create_document', 'update_document'])

    def test_file_hash_or_attachment_readback_mismatch_prevents_course_update(self):
        for flag in ('bad_hash', 'bad_file_readback'):
            client = Client(); setattr(client, flag, True)
            with self.subTest(flag=flag), self.assertRaisesRegex(Stop, '^cover_file_readback_invalid$'):
                covers.sync_cover(client, 618, png(), 'png', apply=True)
            self.assertIsNone(client.course['image'])
            self.assertEqual([tool for tool, _ in client.mutations], ['create_document'])

    def test_concurrent_manual_cover_change_is_never_overwritten(self):
        for flag, error in [('change_on_create', 'cover_course_changed'), ('race_at_update', 'cover_write_uncertain')]:
            client = Client(); setattr(client, flag, True)
            with self.subTest(flag=flag), self.assertRaisesRegex(Stop, '^' + error + '$'):
                covers.sync_cover(client, 618, png(), 'png', apply=True)
            self.assertEqual(client.course['image'], '/files/manual-cover.png')
            self.assertEqual(len(client.files), 1)

    def test_unexpected_course_content_change_is_fatal_on_readback(self):
        client = Client(); client.change_content = True
        with self.assertRaisesRegex(Stop, '^cover_course_readback_invalid$'):
            covers.sync_cover(client, 618, png(), 'png', apply=True)
        self.assertEqual(len(client.files), 1)

    def test_mutation_helper_rejects_every_other_write_operation(self):
        client = Client()
        for tool, arguments in [('delete_document', {}), ('call_method', {}),
                                 ('update_document', {'doctype': 'LMS Course', 'name': 'target-course', 'data': {'published': 1}})]:
            with self.subTest(tool=tool), self.assertRaisesRegex(Stop, '^cover_mutation_not_allowed$'):
                covers._write(client, tool, arguments)
        self.assertEqual(client.mutations, [])


if __name__ == '__main__': unittest.main()

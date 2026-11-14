import copy
import hashlib
import io
import json
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from importer import Stop
import verify_reviewed_shared_image as subject


class Client:
    site, account = subject.SITE, subject.ACCOUNT

    def __init__(self):
        self.calls, self.raw, self.auth = [], b'synthetic image', {'Cookie': 'synthetic'}
        self.course = {'name': 'course634', 'custom_avo_account': 'mastervision',
            'custom_avo_id': '634', 'custom_lms_id': '634', 'published': 0}
        self.lesson = {'name': 'lesson7364', 'course': 'course634', 'custom_avo_account': 'mastervision',
            'custom_avo_id': '7364', 'custom_lms_id': '7364', 'is_draft': 1,
            'include_in_preview': 0, 'owner': 'Administrator'}
        self.blocks = [{'type': 'image', 'data': {'file': {'url': subject.PINNED_TARGET_PATH}}},
            {'type': 'paragraph', 'data': {'text': '<a href="https://' + self.site
                + subject.PINNED_TARGET_PATH + '">Image</a>'}}]
        self.file = {'name': 'file7364', 'file_name': subject.PINNED_TARGET_PATH.rsplit('/', 1)[1],
            'file_url': subject.PINNED_TARGET_PATH, 'file_size': len(self.raw),
            'content_hash': hashlib.md5(self.raw).hexdigest(), 'owner': 'Administrator',
            'is_private': 1, 'attached_to_doctype': 'Course Lesson',
            'attached_to_name': self.lesson['name'], 'attached_to_field': 'body'}
        self.opener = SimpleNamespace(open=self.open)

    def open(self, request, timeout):
        self.calls.append(('GET', request.full_url))
        response = io.BytesIO(self.raw); response.status = 200
        return response

    def call(self, method, args):
        self.calls.append((method, args['doctype']))
        if method == 'get_document':
            return {**self.lesson, 'body': json.dumps({'blocks': self.blocks})}
        rows = {'LMS Course': [self.course], 'Course Lesson': [self.lesson], 'File': [self.file]}[args['doctype']]
        return {'documents': copy.deepcopy(rows), 'has_next_page': False}


class SharedImageTargetTests(unittest.TestCase):
    def invoke(self, client):
        raw = b'synthetic image'
        with patch.multiple(subject, IMAGE_SIZE=len(raw), IMAGE_MD5=hashlib.md5(raw).hexdigest(),
                            IMAGE_SHA256=hashlib.sha256(raw).hexdigest()):
            return subject.verify_reviewed_shared_image_target(client, '634', '7364')

    def test_readonly_proves_own_attachment_link_image_owner_and_actual_bytes(self):
        client = Client(); result = self.invoke(client)
        self.assertEqual(result['code'], 'reviewed_shared_image_verified')
        self.assertTrue(all(method in ('list_documents', 'get_document', 'GET') for method, _ in client.calls))
        self.assertEqual(client.calls[-1][1], 'https://' + client.site + subject.PINNED_TARGET_PATH)

    def test_unrelated_imports_do_no_work(self):
        self.assertIsNone(subject.verify_reviewed_shared_image_target(None, 634, 7363))
        self.assertIsNone(subject.verify_reviewed_shared_image_target(None, 640, 7415))

    def test_wrong_account_site_lesson_course_or_draft_fails(self):
        for owner, key, value in (('client', 'site', 'my-lk.iomp.ru'),
            ('client', 'account', 'mv-centr'), ('lesson', 'course', 'other'),
            ('lesson', 'owner', 'other'), ('lesson', 'is_draft', 0)):
            client = Client()
            if owner == 'client': setattr(client, key, value)
            else: client.lesson[key] = value
            with self.subTest(key=key), self.assertRaisesRegex(Stop, subject.CODE): self.invoke(client)

    def test_new_file_must_match_link_even_when_previous_courses_share_it(self):
        for key, value in (('file_url', '/private/files/renamed.jpg'), ('owner', 'other'),
            ('is_private', 0), ('attached_to_name', 'lesson7363'),
            ('attached_to_field', 'instructor_content'), ('content_hash', '0' * 32),
            ('file_size', 999)):
            client = Client(); client.file[key] = value
            with self.subTest(key=key), self.assertRaisesRegex(Stop, subject.CODE): self.invoke(client)

    def test_missing_or_changed_or_duplicate_link_and_wrong_native_image_fail(self):
        for change in ('missing', 'different', 'duplicate', 'image'):
            client = Client()
            if change == 'missing': client.blocks.pop()
            elif change == 'different': client.blocks[1]['data']['text'] = '<a href="https://example.org">Image</a>'
            elif change == 'duplicate': client.blocks.append(copy.deepcopy(client.blocks[1]))
            else: client.blocks[0]['data']['file']['url'] = '/private/files/other.jpg'
            with self.subTest(change=change), self.assertRaisesRegex(Stop, subject.CODE): self.invoke(client)

    def test_byte_mismatch_and_failed_get_stop_without_any_write(self):
        client = Client(); client.raw = b'wrong'
        with self.assertRaisesRegex(Stop, subject.CODE): self.invoke(client)
        client = Client(); client.opener.open = lambda *args, **kwargs: (_ for _ in ()).throw(OSError())
        with self.assertRaisesRegex(Stop, '^reviewed_shared_image_readback_unavailable$'): self.invoke(client)

    def test_controller_does_not_mark_complete_when_created_or_resumed_image_fails(self):
        import test_run as controller
        source = [{**controller.payload(634), 'lesson_id': 7364}]
        for created in (False, True):
            def importing(target, payloads, apply=False, images_for_lesson=None, progress_callback=None):
                if created:
                    progress_callback({'course_id': 634, 'lesson_id': 7364, 'status': 'write_started'})
                    progress_callback({'course_id': 634, 'lesson_id': 7364, 'status': 'created'})
                return {'status': 'already_present', 'warnings': [], 'created_lesson_ids': []}
            with patch.object(controller.mod, 'stored_course', return_value=source), \
                 patch.object(controller.mod, 'prepare_payloads', return_value=(source, [])), \
                 patch.object(controller.FakeImporter, 'import_course', importing), \
                 patch.object(subject, 'verify_reviewed_shared_image_target', side_effect=Stop(subject.CODE)):
                result = controller.ControllerTests().invoke(634,
                    args=['--stored', '--apply', '--course', '634'])
            self.assertEqual(result[0], 1); self.assertEqual(result[1].marks, [])
            self.assertTrue(any(event.get('status') == 'stopped' for event in result[5]))


if __name__ == '__main__': unittest.main()

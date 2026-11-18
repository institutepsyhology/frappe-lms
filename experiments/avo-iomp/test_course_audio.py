import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
import re
import unittest
from unittest.mock import patch

import import_capture
import course_audio
import course_audio_worker as worker


ROW = {'lesson_id': '1829', 'url': 'https://f1.autoweboffice.ru/example/audio.mp3'}
MP3 = b'ID3\x04\x00\x00\x00\x00\x00\x00audio'


class FixtureFile(SimpleNamespace):
    def insert(self):
        self.name = 'test-file'
        self.file_size = len(self.content)
        self.content_hash = hashlib.md5(self.content, usedforsecurity=False).hexdigest()
        self.file_url = '/private/files/' + self.file_name
        self.db.files[self.name] = self
        return self

    def get_content(self, encodings):
        return self.content

    def save(self):
        return self


class FixtureDB:
    def __init__(self):
        self.files = {}
        self.shared = []
        self.course = SimpleNamespace(name='test-course', published=0, custom_avo_account='iomp',
                                      custom_avo_id='91', custom_lms_id='91')
        self.lesson = SimpleNamespace(name='test-lesson', course='test-course', is_draft=1, include_in_preview=0,
                                      custom_avo_account='iomp', custom_avo_id='1829', custom_lms_id='1829',
                                      content=json.dumps({'blocks': [{'type': 'paragraph', 'data': {
                                          'text': '<a href="https://' + worker.SITE + worker.target(ROW)
                                          + '">Аудиозапись</a>'}}]}, ensure_ascii=False))

    def get_all(self, doctype, filters, pluck, limit_page_length):
        if doctype == 'DocShare':
            return self.shared
        docs = {'File': self.files.values(), 'LMS Course': [self.course], 'Course Lesson': [self.lesson]}[doctype]
        return [doc.name for doc in docs if all(getattr(doc, k) == v for k, v in filters.items())]

    def get_doc(self, doctype, name=None):
        if isinstance(doctype, dict):
            return FixtureFile(**doctype, db=self, owner='Administrator', is_folder=0,
                               attached_to_field=None, attached_to_doctype=None, attached_to_name=None)
        if doctype == 'File':
            return self.files[name]
        return {'Course Lesson': self.lesson, 'LMS Course': self.course}[doctype]


class AudioTests(unittest.TestCase):
    def test_prepare_and_attach_can_resume_without_another_download(self):
        db = FixtureDB()
        with patch.object(worker, 'download', return_value=MP3) as fetch:
            for mode in ('prepare', 'prepare', 'attach', 'attach', 'prepare'):
                worker.sync_one(db, ROW, mode, worker.MAX_SIZE, Path(__file__).parent)
            fetch.assert_called_once()
        file, = db.files.values()
        self.assertEqual((file.is_private, file.attached_to_doctype, file.attached_to_name, file.attached_to_field),
                         (1, 'Course Lesson', db.lesson.name, 'content'))

    def test_foreign_or_shared_blob_is_not_attached_even_on_resume(self):
        db = FixtureDB()
        with patch.object(worker, 'download', return_value=MP3):
            path = Path(__file__).parent
            worker.sync_one(db, ROW, 'prepare', worker.MAX_SIZE, path)
            file, = db.files.values()
            for attr, value, message in [('owner', 'someone', 'identity'), ('is_private', 0, 'identity'),
                                         ('attached_to_name', 'wrong', 'conflict'), ('content', b'bad', 'readback')]:
                with self.subTest(attr=attr), patch.object(file, attr, value), self.assertRaisesRegex(worker.AudioError, message):
                    worker.sync_one(db, ROW, 'attach', worker.MAX_SIZE, path)
            for attr, value in [('course', 'other'), ('content', '{}'), ('custom_avo_account', 'other')]:
                with self.subTest(attr=attr), patch.object(db.lesson, attr, value), self.assertRaises(worker.AudioError):
                    worker.sync_one(db, ROW, 'attach', worker.MAX_SIZE, path)
            with patch.object(db, 'shared', ['share']), self.assertRaisesRegex(worker.AudioError, 'identity'):
                worker.sync_one(db, ROW, 'attach', worker.MAX_SIZE, path)
            self.assertIsNone(file.attached_to_name)

    def test_only_the_reviewed_sources_can_reach_server_download(self):
        with self.assertRaisesRegex(worker.AudioError, 'manifest_changed'):
            worker.check_manifest([ROW] * 62)
        for src in (ROW['url'].replace('f1.autoweboffice.ru', 'shop.mastervision.su'),
                    ROW['url'].replace('https:', 'http:'), ROW['url'] + '?x=1'):
            with self.subTest(src=src), self.assertRaises(worker.AudioError):
                worker.target({**ROW, 'url': src})
        with self.assertRaises(worker.AudioError):
            worker.target({**ROW, 'lesson_id': '1839'})

    def test_actual_capture_keeps_audio_order_and_all_media(self):
        captures = sorted((import_capture.ARCHIVE / 'course-91').glob('*/course.json'))
        if not captures:
            self.skipTest('private IOMP capture unavailable')
        _, _, payloads = import_capture.read_capture(captures[-1].parent)
        def leaves(node):
            yield node
            for child in node.get('children', []):
                yield from leaves(child)
        source = {p['lesson_id']: [n['fields']['audioSrc'] for n in leaves(p['ape']) if n['name'] == 'audio']
                  for p in payloads if p['lesson_id'] in course_audio.LESSONS}
        def frames(p):
            return [src for node in leaves(p['ape'])
                    for src in re.findall(r'<iframe src="(https://drive\.google\.com/[^"]+)"',
                                          node.get('fields', {}).get('html') or '')]
        original_frames = {p['lesson_id']: frames(p) for p in payloads if p['lesson_id'] in source}
        rows = course_audio.prepare_course_audio(payloads)
        self.assertEqual(len(rows), 62)
        image_count = frame_count = 0
        for p in payloads:
            lesson = p['lesson_id']
            if lesson not in source:
                continue
            images = {}
            self.assertEqual(frames(p), original_frames[lesson])
            for node in leaves(p['ape']):
                if node['name'] == 'image' and not import_capture.omit_placeholder_node(node, 'iomp', '91', lesson):
                    images[node['id']] = '/private/files/avo-test.jpg'
                html = node.get('fields', {}).get('html') or ''
                frame_count += html.count('<iframe src="https://drive.google.com')
            plan = import_capture.plan_import(p, images)
            self.assertEqual(plan['issues'], [], lesson)
            image_count += sum(block['type'] == 'image' for block in plan['blocks'])
            hrefs = [block['data']['text'] for block in plan['blocks']
                     if block['type'] == 'paragraph' and '/private/files/avo-iomp-91-' in block['data']['text']]
            self.assertEqual(len(hrefs), len(source[lesson]))
            for href, url in zip(hrefs, source[lesson]):
                self.assertIn('https://' + worker.SITE + worker.target({'lesson_id': lesson, 'url': url}), href)
        self.assertEqual((image_count, frame_count), (12, 8))


if __name__ == '__main__':
    unittest.main()

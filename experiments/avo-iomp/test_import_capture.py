import hashlib
import json
import unittest
from pathlib import Path
from unittest.mock import patch

from import_capture import Stop, normalize_avatar_label, refreshed_lessons
from lms.lms.avo_transform import omit_placeholder_node
from normalize_review import EXCLUDED_LESSONS, clean_timing_table, normalize_review


class AvatarNormalizationTests(unittest.TestCase):
    def test_only_the_known_avatar_loses_the_generic_image_label(self):
        avatar = 'https://example.test/avatar.jpeg'
        picture = 'https://example.test/lesson.png'
        avatar_hash = hashlib.sha256(avatar.encode()).hexdigest()
        nodes = [
            {'name': 'image', 'fields': {'anchor': '', 'imageSrc': avatar, 'html': 'Изображение'}},
            {'name': 'image', 'fields': {'anchor': '', 'imageSrc': picture, 'html': 'Изображение'}},
            {'name': 'image', 'fields': {'anchor': '', 'imageSrc': avatar, 'html': 'Схема урока'}},
            {'name': 'text', 'fields': {'html': '<p>Здравствуйте, {name}</p>'}},
        ]
        payload = {'course_id': '3', 'lesson_id': '424', 'ape': {'name': 'page', 'children': nodes}}
        with patch('lms.lms.avo_transform.PLACEHOLDER_IMAGE_SHA256', avatar_hash):
            normalize_avatar_label(payload)
            self.assertTrue(omit_placeholder_node(nodes[0], 'iomp', '3', '424'))
            self.assertEqual(nodes[1]['fields']['html'], 'Изображение')
            self.assertEqual(nodes[2]['fields']['html'], 'Схема урока')
            self.assertTrue(omit_placeholder_node(nodes[3], 'iomp', '3', '424'))


class ReviewedContentTests(unittest.TestCase):
    def test_only_owner_selected_material_buttons_are_omitted(self):
        for course_id, lesson_id, label in (
            ('63', '537', 'АУДИОЗАПИСЬ'),
            ('97', '1277', 'ПРЕЗЕНТАЦИЯ'),
        ):
            with self.subTest(lesson_id=lesson_id):
                button = {'name': 'button', 'fields': {
                    'html': label, 'linkType': 'url', 'url': 'https://example.test/material',
                }}
                video = {'name': 'video', 'fields': {'videoProvider': 'youtube'}}
                payload = {'account': 'iomp', 'source_origin': 'https://shop.iomp.ru', 'format': 'ape',
                           'course_id': course_id, 'lesson_id': '1',
                           'ape': {'name': 'page', 'children': [video, button]}}
                normalize_review(payload)
                self.assertEqual(payload['ape']['children'], [video, button])
                payload['lesson_id'] = lesson_id
                normalize_review(payload)
                self.assertEqual(payload['ape']['children'], [video])

    def test_reviewed_video_poster_is_omitted_without_changing_player(self):
        poster = 'https://youtu.be/aaaaaaaaaaa'
        player = 'https://youtu.be/bbbbbbbbbbb'
        fields = {'videoProvider': 'youtube', 'videoSrc': player, 'posterSrc': poster}
        video = {'name': 'video', 'fields': fields}
        payload = {'account': 'iomp', 'source_origin': 'https://shop.iomp.ru', 'format': 'ape',
                   'course_id': '38', 'lesson_id': '1841', 'ape': {'name': 'page', 'children': [video]}}
        with patch('normalize_review.STALE_POSTER_DIGEST', hashlib.sha256(poster.encode()).hexdigest()):
            normalize_review(payload)
            self.assertEqual(fields, {'videoProvider': 'youtube', 'videoSrc': player})
            fields['posterSrc'] = 'https://example.test/poster.jpg'
            normalize_review(payload)
            self.assertEqual(fields['posterSrc'], 'https://example.test/poster.jpg')

    def test_drive_file_button_gets_https_and_empty_presentation_is_omitted(self):
        drive = 'drive.google.com/file/d/sample-id/view?usp=sharing'
        nodes = [
            {'name': 'button', 'fields': {'html': 'ПРЕЗЕНТАЦИЯ', 'linkType': 'url', 'url': ''}},
            {'name': 'button', 'fields': {'html': 'ПРЕЗЕНТАЦИЯ', 'linkType': 'url', 'url': drive}},
            {'name': 'button', 'fields': {'html': 'АУДИОЗАПИСЬ', 'linkType': 'url', 'url': drive + '&extra=1'}},
        ]
        payload = {'account': 'iomp', 'source_origin': 'https://shop.iomp.ru', 'format': 'ape',
                   'course_id': '74', 'lesson_id': '736', 'ape': {'name': 'page', 'children': nodes}}
        normalize_review(payload)
        self.assertEqual([node['fields']['url'] for node in payload['ape']['children']],
                         ['https://' + drive, drive + '&extra=1'])

    def test_table_repairs_keep_text_cells_and_links(self):
        source = '<table cellpadding="3"><tbody><tr><td valign="middle"><a id="start"></a>00:01</td>' \
                 '<td><a href="https://example.test/material">Материал</a></td></tr></tbody></table>'
        result = clean_timing_table(source)
        self.assertIn('<span id="start"></span>00:01', result)
        self.assertIn('<a href="https://example.test/material">Материал</a>', result)
        self.assertNotIn('cellpadding', result)
        self.assertNotIn('valign', result)

    def test_heading_keeps_its_link_and_blank_audio_is_omitted(self):
        heading = '<h4 style="text-align: center"><a href="https://example.test/audio">Аудио</a></h4>'
        nodes = [
            {'name': 'header', 'fields': {'anchor': '', 'format': 'h4', 'html': heading}},
            {'name': 'button', 'fields': {'html': 'АУДИОЗАПИСЬ', 'linkType': 'url', 'url': ''}},
            {'name': 'button', 'fields': {'html': 'АУДИОЗАПИСЬ', 'linkType': 'url', 'url': 'https://example.test/audio'}},
        ]
        payload = {'account': 'iomp', 'source_origin': 'https://shop.iomp.ru', 'format': 'ape',
                   'course_id': '8', 'lesson_id': '32', 'course_title': 'Course', 'lesson_title': 'Lesson',
                   'ape': {'name': 'page', 'children': nodes}}
        normalize_review(payload)
        updated, button = payload['ape']['children']
        self.assertEqual((updated['name'], updated['fields']['html']), ('text', heading))
        self.assertEqual(button['fields']['url'], 'https://example.test/audio')
        self.assertIn('5296', EXCLUDED_LESSONS)
        self.assertIn('4396', EXCLUDED_LESSONS)
        payload.update(course_id='34', lesson_id='1792')
        normalize_review(payload)
        self.assertEqual(payload['ape']['children'], [updated])


class RefreshReceiptTests(unittest.TestCase):
    def test_new_full_snapshot_supersedes_only_earlier_partial_snapshots(self):
        course = Path('course-74')
        capture = course / '2026-11-18T18-04-00-000Z'
        old = course / 'refreshed' / '2026-11-18T18-03-00-000Z' / 'refresh-status.json'
        new = course / 'refreshed' / '2026-11-18T18-05-00-000Z' / 'refresh-status.json'
        with (patch.object(Path, 'glob', return_value=[old, new]),
              patch.object(Path, 'read_text', return_value=json.dumps({
                  'account': 'iomp', 'course_id': 74, 'lesson_ids': [714], 'refreshed': [714],
              })) as read):
            self.assertEqual(refreshed_lessons(capture, '74', [714]),
                             {'714': new.parent / 'lesson-714.json'})
            read.assert_called_once_with(encoding='utf-8')
            with self.assertRaisesRegex(Stop, 'refreshed_outline_mismatch'):
                refreshed_lessons(capture, '74', [714, 715])


if __name__ == '__main__':
    unittest.main()

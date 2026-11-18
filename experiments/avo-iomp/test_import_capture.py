import hashlib
import unittest
from unittest.mock import patch

from import_capture import normalize_avatar_label
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


if __name__ == '__main__':
    unittest.main()

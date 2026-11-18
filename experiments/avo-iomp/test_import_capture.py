import hashlib
import unittest
from unittest.mock import patch

from import_capture import normalize_avatar_label
from lms.lms.avo_transform import omit_placeholder_node


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


if __name__ == '__main__':
    unittest.main()

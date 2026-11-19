import copy
import hashlib
import unittest
from unittest.mock import patch

import import_capture
import normalize_course193 as material


def record(lesson, node):
    return {'account': 'iomp', 'source_origin': 'https://shop.iomp.ru', 'format': 'ape',
            'course_id': '193', 'lesson_id': lesson, 'course_title': 'Курс', 'lesson_title': 'Урок',
            'ape': {'name': 'page', 'children': [node]}}


class Course193Tests(unittest.TestCase):
    def test_label_keeps_word_boundary_and_destination(self):
        for original, expected in [
            ('<span style="font-size: 16px; line-height: 1.4">П</span>ОДРОБНЕЕ', 'ПОДРОБНЕЕ'),
            ('АУДИОЗАПИСЬ<span style="font-size: 16px"> 2</span>', 'АУДИОЗАПИСЬ 2'),
        ]:
            with self.subTest(original=original):
                fields = {'html': original, 'url': 'https://example.org/file', 'linkType': 'url', 'blank': True}
                expected_fields = {**fields, 'html': expected}
                node = {'name': 'button', 'fields': fields}
                payload = record('3279', node)
                material.normalize_course193(payload)
                self.assertEqual(fields, expected_fields)
                saved = copy.deepcopy(payload)
                material.normalize_course193(payload)
                self.assertEqual(saved, payload)

    def test_scoped_and_unknown_button_styles(self):
        original = '<span style="font-size: 16px">ТЕКСТ</span>'
        for overrides, label in [
            ({'course_id': '219'}, original), ({'lesson_id': '3260'}, original),
            ({'source_origin': 'https://shop.mastervision.su'}, original),
            ({'account': 'mv-centr'}, original), ({}, '<span style="display:none">ЛИЧНОЕ</span>'),
        ]:
            payload = record('3279', {'name': 'button', 'fields': {
                'html': label, 'url': 'https://example.org/file', 'linkType': 'url'}})
            payload.update(overrides)
            saved = copy.deepcopy(payload)
            material.normalize_course193(payload)
            self.assertEqual(saved, payload)

    def test_timing_keeps_headers_cells_list_numbers_and_links(self):
        html = ('<p>ТАЙМИНГ</p><table><thead><tr><th style="vertical-align:top" scope="col">Время</th>'
                '</tr></thead><tbody><tr><td><ol start="2"><li>00:30 <a href="https://example.org/file">'
                'Глава</a></li></ol></td></tr></tbody></table>')
        payload = record('3272', {'name': 'text', 'fields': {'html': html}})
        with patch.dict(material.TIMING_DIGESTS, {'3272': hashlib.sha256(html.encode()).hexdigest()}):
            changed = copy.deepcopy(payload)
            changed['ape']['children'][0]['fields']['html'] += '<p>Новое</p>'
            saved = copy.deepcopy(changed)
            material.normalize_course193(changed)
            self.assertEqual(saved, changed)
            material.normalize_course193(payload)
        candidate = payload['ape']['children'][0]['fields']['html']
        self.assertIn('<ol start="2">', candidate)
        self.assertEqual(material.table_content(html), material.table_content(candidate))
        self.assertFalse(import_capture.plan_import(payload)['issues'])

    def test_missing_image_keeps_its_timecode_and_neighbors(self):
        wrapper = ('<span style="display:inline-block"><span style="overflow:hidden"><span style="width:602px">'
                   '<span style="height:300px"><img width="602" height="300" '
                   'src="https://lh7-us.googleusercontent.com/example" /></span></span></span></span>')
        html = '<p>00.12.38 ' + wrapper + '</p><p>00.21.32 Следующий вопрос</p>'
        payload = record('3268', {'name': 'text', 'fields': {'html': html}})
        with patch.dict(material.TIMING_DIGESTS, {'3268': hashlib.sha256(html.encode()).hexdigest()}):
            material.normalize_course193(payload)
        candidate = payload['ape']['children'][0]['fields']['html']
        self.assertEqual(candidate, html.replace(wrapper, ''))
        self.assertFalse(import_capture.plan_import(payload)['issues'])

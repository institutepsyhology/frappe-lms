import base64
import copy
import json
import unittest
from unittest.mock import patch

from import_capture import ARCHIVE, Review
from lms.lms.avo_transform import plan_import
from normalize_reviewed_vk import normalize_reviewed_vk, section_digest


def caption(label):
    return {'name': 'text', 'fields': {
        'html': '<p style="text-align: center;"><span style="color:#ffffff;"><strong>'
                + label + '</strong></span></p>',
    }}


def sample():
    frame = ('<iframe src="https://vkvideo.ru/video_ext.php?oid=-123&amp;id=456&amp;hd=2'
             '&amp;hash=0123456789abcdef" width="853" height="480" allow="autoplay; encrypted-media; '
             'fullscreen; picture-in-picture; screen-wake-lock;" frameborder="0" allowfullscreen></iframe>')
    main = {'name': 'video', 'fields': {'videoProvider': 'youtube', 'videoSrc': 'https://youtu.be/aaaaaaaaaaa'}}
    vk = {'name': 'video', 'fields': {'videoProvider': 'embedded', 'embeddedHtml': frame}}
    group = {'name': 'section', 'children': [
        {'name': 'column', 'children': [caption('ОСНОВНОЙ ПЛЕЕР'), main]},
        {'name': 'column', 'children': [caption('АЛЬТЕРНАТИВНЫЙ ПЛЕЕР'), vk]},
    ]}
    payload = {'account': 'iomp', 'source_origin': 'https://shop.iomp.ru', 'format': 'ape',
               'course_id': '48', 'lesson_id': '263', 'course_title': 'Course', 'lesson_title': 'Lesson',
               'ape': {'name': 'page', 'children': [{'name': 'section', 'children': []}, group]}}
    return payload, group, frame


class ReviewedVkTests(unittest.TestCase):
    def test_safe_iframe_keeps_both_choices_and_their_order(self):
        payload, group, frame = sample()
        with patch('normalize_reviewed_vk.SOURCE_SECTION', section_digest(group)):
            normalize_reviewed_vk(payload)
        plan = plan_import(payload, {})
        self.assertEqual(plan['issues'], [])
        primary_label, primary, alternative_label, alternative = plan['blocks']
        self.assertEqual([item['type'] for item in plan['blocks']], ['header', 'videoChoice', 'header', 'htmlBlock'])
        self.assertEqual(primary_label['data']['text'], '<strong>ОСНОВНОЙ ПЛЕЕР</strong>')
        self.assertEqual(primary['data']['youtube'], 'https://youtu.be/aaaaaaaaaaa')
        self.assertEqual(alternative_label['data']['text'], '<strong>АЛЬТЕРНАТИВНЫЙ ПЛЕЕР</strong>')
        self.assertEqual(base64.b64decode(alternative['data']['encodedHtml']).decode(), frame)

    def test_changed_source_and_rejected_frame_leave_every_field_intact(self):
        payload, group, frame = sample()
        before = copy.deepcopy(payload)
        with self.assertRaisesRegex(Review, 'reviewed_vk_source_changed'):
            normalize_reviewed_vk(payload)
        self.assertEqual(payload, before)
        fields = group['children'][1]['children'][1]['fields']
        fields['embeddedHtml'] = frame.replace('vkvideo.ru/', 'example.test/')
        before = copy.deepcopy(payload)
        with patch('normalize_reviewed_vk.SOURCE_SECTION', section_digest(group)):
            with self.assertRaisesRegex(Review, 'reviewed_vk_frame_invalid'):
                normalize_reviewed_vk(payload)
        self.assertEqual(payload, before)

    def test_other_sources_are_untouched(self):
        for field, other in [('account', 'mv-centr'), ('source_origin', 'https://example.test'),
                             ('course_id', '49'), ('lesson_id', '264'), ('format', 'preview')]:
            with self.subTest(field=field):
                payload, _, _ = sample()
                payload[field] = other
                before = copy.deepcopy(payload)
                normalize_reviewed_vk(payload)
                self.assertEqual(payload, before)

    def test_current_private_capture_keeps_the_presentation_and_replays_identically(self):
        captures = sorted((ARCHIVE / 'course-48' / 'refreshed').glob('*/lesson-263.json'))
        if not captures:
            self.skipTest('private capture unavailable')
        payload = json.loads(captures[-1].read_text(encoding='utf-8'))['payload']
        payload.update(course_id='48', lesson_id='263')
        original = copy.deepcopy(payload['ape']['children'])
        normalize_reviewed_vk(payload)
        children = payload['ape']['children']
        self.assertEqual(children[:1] + children[2:], original[:1] + original[2:])
        self.assertEqual(children[1]['children'][0]['children'][1], original[1]['children'][0]['children'][1])
        frozen = copy.deepcopy(payload)
        normalize_reviewed_vk(payload)
        self.assertEqual(payload, frozen)
        plan = plan_import(payload, {})
        self.assertEqual(plan['issues'], [])
        self.assertEqual([b['type'] for b in plan['blocks']],
                         ['header', 'videoChoice', 'header', 'htmlBlock', 'paragraph'])
        self.assertIn('Презентация', plan['blocks'][-1]['data']['text'])

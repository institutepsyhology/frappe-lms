import copy
import hashlib
from html import escape
import json
from pathlib import Path
import unittest
from unittest.mock import patch

import import_capture
import normalize_offer_links as offers


class PreviewOfferTests(unittest.TestCase):
    def setUp(self):
        self.archive = Path('fixture')
        reader = patch.object(Path, 'read_text', side_effect=FileNotFoundError)
        self.read_text = reader.start()
        self.addCleanup(reader.stop)
        self.key = ('178', '3002')
        self.placeholder = '{goods_ordering_738}'
        self.url = 'https://shop.iomp.ru/?r=ordering/cart/as1&id=738&clean=true&lg=ru'
        self.button = {'name': 'button', 'fields': {'html': 'Записаться', 'linkType': 'url',
                       'url': self.placeholder, 'blank': True}}
        self.payload = {'account': 'iomp', 'source_origin': offers.ORIGIN, 'format': 'ape', 'course_id': '178',
                        'lesson_id': '3002', 'course_title': 'Курс', 'lesson_title': 'Урок',
                        'ape': {'name': 'page', 'children': [self.button]}}
        for mapping, item in [(offers.SOURCE_BUTTONS, (self.placeholder, offers._digest(self.button))),
                              (offers.PREVIEW_FINGERPRINTS, hashlib.sha256(self.url.encode()).hexdigest())]:
            change = patch.dict(mapping, {self.key: item})
            change.start()
            self.addCleanup(change.stop)
        self.row = {'course_id': 178, 'lesson_id': 3002, 'url': self.url}
        self.capture = {'account': 'iomp', 'source_origin': offers.ORIGIN, 'links': [self.row]}

    def write_capture(self, **changes):
        self.read_text.side_effect = None
        self.read_text.return_value = json.dumps({**self.capture, **changes})

    def test_link_keeps_caption_and_builds_a_clickable_lesson(self):
        self.write_capture()
        expected = copy.deepcopy(self.payload)
        expected['ape']['children'][0]['fields']['url'] = self.url
        offers.resolve_offer_link(self.payload, self.archive)
        offers.resolve_offer_link(self.payload, self.archive)
        self.assertEqual(self.payload, expected)
        plan = import_capture.plan_import(self.payload)
        self.assertEqual(plan['issues'], [])
        self.assertIn('href="' + escape(self.url, quote=True) + '"', plan['blocks'][0]['data']['text'])

    def test_mismatch_missing_or_ambiguous_preview_is_rejected(self):
        with self.assertRaisesRegex(import_capture.Review, 'preview_requires_verification'):
            offers.resolve_offer_link(self.payload, self.archive)
        for changes in [
            {'account': 'mastervision'}, {'source_origin': 'https://shop.mv-centr.ru'},
            {'links': [{**self.row, 'course_id': 194}]}, {'links': [self.row, self.row]},
            {'links': [{**self.row, 'url': self.url + '?account=someone'}]},
        ]:
            self.write_capture(**changes)
            with self.assertRaisesRegex(import_capture.Review, 'preview_requires_verification'):
                offers.resolve_offer_link(self.payload, self.archive)
        self.assertEqual(self.button['fields']['url'], self.placeholder)

    def test_even_a_matching_hash_cannot_allow_a_personal_preview_url(self):
        for suffix in ['&id_contact=123', '&id_contact_vc=secret', '&id=738', '#account']:
            url = self.url + suffix
            self.write_capture(links=[{**self.row, 'url': url}])
            with patch.dict(offers.PREVIEW_FINGERPRINTS, {self.key: hashlib.sha256(url.encode()).hexdigest()}):
                with self.assertRaisesRegex(import_capture.Review, 'preview_requires_verification'):
                    offers.resolve_offer_link(self.payload, self.archive)

    def test_same_caption_cannot_substitute_another_product_or_form(self):
        for url in (self.url.replace('id=738', 'id=750'), self.url.replace('cart/as1', 'cart/checkout')):
            self.write_capture(links=[{**self.row, 'url': url}])
            with patch.dict(offers.PREVIEW_FINGERPRINTS, {self.key: hashlib.sha256(url.encode()).hexdigest()}):
                with self.assertRaisesRegex(import_capture.Review, 'preview_requires_verification'):
                    offers.resolve_offer_link(self.payload, self.archive)

    def test_new_receipt_is_separate_from_previous_three_links(self):
        key = ('179', '3017')
        self.assertNotIn(key, offers.FIRST_CAPTURE)
        self.payload.update(course_id=key[0], lesson_id=key[1])
        self.button['fields']['url'] = '{goods_ordering_746}'
        self.row.update(course_id=179, lesson_id=3017, url=self.url.replace('738', '746'))
        paths = []
        def read_receipt(path, **kwargs):
            paths.append(path)
            return json.dumps(self.capture)

        with patch.object(Path, 'read_text', read_receipt), patch.dict(
                offers.SOURCE_BUTTONS, {key: ('{goods_ordering_746}', offers._digest(self.button))}):
            offers.resolve_offer_link(self.payload, self.archive)
        self.assertEqual(self.button['fields']['url'], self.row['url'])
        self.assertEqual(paths, [self.archive / 'preview-offer-links-20261120.json'])

    def test_other_lessons_and_schools_are_untouched(self):
        for changes in [
            {'account': 'mastervision'}, {'source_origin': 'https://shop.mv-centr.ru'},
            {'course_id': 194}, {'lesson_id': '3532'},
        ]:
            other = {**copy.deepcopy(self.payload), **changes}
            before = copy.deepcopy(other)
            offers.resolve_offer_link(other, self.archive)
            self.assertEqual(other, before)

    def test_unreviewed_source_button_is_rejected(self):
        self.write_capture()
        self.button['fields']['html'] = 'Другой материал'
        with self.assertRaisesRegex(import_capture.Review, 'button_changed'):
            offers.resolve_offer_link(self.payload, self.archive)
        self.assertEqual(self.button['fields']['url'], self.placeholder)

    def test_only_owner_excluded_lesson_in_course_208(self):
        self.assertIn('3532', import_capture.EXCLUDED_LESSONS)
        self.assertNotIn('3526', import_capture.EXCLUDED_LESSONS)


class PrivateOfferCaptureTests(unittest.TestCase):
    def test_confirmed_links_are_present_once_in_real_lessons(self):
        archive = import_capture.ARCHIVE
        if not (archive / 'preview-offer-links.json').is_file():
            self.skipTest('private preview captures unavailable')
        for (course, lesson), (placeholder, _) in offers.SOURCE_BUTTONS.items():
            with self.subTest(course=course, lesson=lesson):
                directory = sorted((archive / f'course-{course}').glob('*/capture-status.json'))[-1].parent
                _, _, records = import_capture.read_capture(directory)
                payload, = [row for row in records if row['lesson_id'] == lesson]
                plan = import_capture.plan_import(payload)
                self.assertFalse(plan['issues'], plan['issues'])
                url = offers._preview_url(archive, (course, lesson))
                content = json.dumps(plan['blocks'], ensure_ascii=False)
                self.assertEqual(content.count(escape(url, quote=True)), 1)
                self.assertFalse(placeholder in content)

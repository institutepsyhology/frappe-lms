"""Keep the reviewed IOMP certificate actions as native LMS buttons."""

import unittest

from import_capture import plan_import


TITLE = 'Скачать СЕРТИФИКАТ'
FORMATTED = '<strong><span style="font-size: 20px">Скачать СЕРТИФИКАТ</span></strong>'
SOURCE = 'https://shop.iomp.ru'


def example(course, lesson, label, *, origin=SOURCE, account='iomp', **changes):
    fields = {'linkType': 'url', 'html': label, 'url': SOURCE + '/personal/certificate',
              'blank': True, **changes}
    return {'format': 'ape', 'account': account, 'source_origin': origin, 'course_id': course,
            'lesson_id': lesson, 'course_title': 'Course', 'lesson_title': 'Lesson',
            'ape': {'name': 'page', 'children': [{'name': 'button', 'fields': fields}]}}


class CertificateButtonsTests(unittest.TestCase):
    def test_exact_reviewed_buttons_keep_action_caption_order_and_target(self):
        for course, lesson, label, tint in [('232', '4299', TITLE, '#ad1457'),
                                           ('233', '4298', TITLE, '#ad1457'),
                                           ('253', '4546', FORMATTED, '#565953')]:
            for blank in [True, False]:
                with self.subTest(course=course, blank=blank):
                    payload = example(course, lesson, label, blank=blank)
                    material = {'name': 'text', 'fields': {'html': '<p>Material</p>'}}
                    payload['ape']['children'].insert(0, material)
                    payload['ape']['children'].append(material.copy())
                    result = plan_import(payload)
                    self.assertTrue(result['ready'], result['issues'])
                    self.assertEqual([b['type'] for b in result['blocks']],
                                     ['paragraph', 'lessonButton', 'paragraph'])
                    self.assertEqual(result['blocks'][1]['data'], {
                        'text': TITLE, 'url': SOURCE + '/personal/certificate',
                        'background': tint, 'color': '#ffffff', 'size': 'medium', 'newTab': blank})

    def test_no_rewrite_outside_reviewed_action(self):
        for changes in [{'course': '233'}, {'lesson': '5000'}, {'account': 'mastervision'},
                        {'origin': 'https://shop.mastervision.su'}, {'label': 'Other'},
                        {'url': SOURCE + '/personal/training'}]:
            with self.subTest(changes=changes):
                payload = example(**({'course': '232', 'lesson': '4299', 'label': TITLE} | changes))
                result = plan_import(payload)
                self.assertEqual([b['type'] for b in result['blocks']], ['paragraph'])

    def test_unknown_action_fields_and_targets_still_require_review(self):
        for changes in [{'blank': 'false'}, {'event': 'unexpected'}, {'linkType': 'action'}]:
            with self.subTest(changes=changes):
                result = plan_import(example('253', '4546', FORMATTED, **changes))
                self.assertIn('unsupported_button', result['issues'])
                self.assertFalse(result['ready'])

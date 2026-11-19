import base64
import copy
import unittest

import import_capture as migration
from masterclass_frame import FRAME, reviewed_content


class ReviewedFrameTests(unittest.TestCase):
    def setUp(self):
        self.source = [{'account':'iomp', 'source_origin':'https://shop.iomp.ru',
                        'course_id':'347', 'lesson_id':'7128', 'format':'ape',
                        'ape':{'name':'page','children':[{'name':'code',
                              'fields':{'anchor':'','html':FRAME + '\n'}}]}}]

    def test_verbatim_single_html_block(self):
        block, = reviewed_content(self.source)['blocks']
        self.assertEqual(block['type'], 'htmlBlock')
        self.assertEqual(base64.b64decode(block['data']['encodedHtml']).decode(), FRAME + '\n')
        self.assertIn('7117', migration.EXCLUDED_LESSONS)

    def test_changed_site_frame_or_additional_content_needs_review(self):
        for case in ('account', 'url', 'attribute', 'sibling', 'child', 'conditional'):
            payload = copy.deepcopy(self.source)
            lesson = payload[0]
            children = lesson['ape']['children']
            node = children[0]
            if case == 'account':
                lesson['account'] = 'mastervision'
            elif case == 'url':
                node['fields']['html'] = FRAME.replace('rasprodaza2026', 'other')
            elif case == 'attribute':
                node['fields']['html'] = FRAME.replace('frameborder', 'data-custom')
            elif case == 'sibling':
                children.append({'name':'text'})
            elif case == 'child':
                node['children'] = [{'name':'button'}]
            else:
                node['visibleConditions'] = {'personalOffer':2}
            with self.subTest(case=case), self.assertRaises(migration.Review):
                reviewed_content(payload)

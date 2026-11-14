"""Static migration HTML accepts bounded material, not arbitrary embed code."""
import base64
import unittest
import copy
import hashlib
import json
from unittest.mock import patch

from lms.lms.avo_html_fragment import make_html_block


class ReviewedEmbedHTMLTests(unittest.TestCase):
    def exact(self, html):
        self.assertEqual(base64.b64decode(make_html_block(html)['data']['encodedHtml']).decode(), html)

    def test_plain_mailto_preserves_authored_contact_link(self):
        self.exact('<p><a href="mailto:author@example.test">Написать автору</a></p>')
        for target in ('mailto:a@example.test?body=secret', 'mailto:a@example.test#fragment',
                       'mailto:a%0d%0abcc:other@example.test', 'mailto:a@example.test,b@example.test',
                       'mailto:a@bad..example.test', 'mailto:a@example.test\n',
                       'javascript:alert(1)', 'data:text/html,hello'):
            with self.subTest(target=target), self.assertRaises(ValueError):
                make_html_block('<a href="' + target + '">Link</a>')

    def test_cell_merges_preserve_layout_and_reject_unbounded_values(self):
        self.exact('<table><tbody><tr><td colspan="2" rowspan="1">A</td></tr></tbody></table>')
        for attr in ('colspan', 'rowspan'):
            for value in ('0', '17', '-1', '1.0', '01', '1 onload=x', ''):
                with self.subTest(attr=attr, value=value), self.assertRaises(ValueError):
                    make_html_block('<table><tr><td ' + attr + '="' + value + '">A</td></tr></table>')
            with self.assertRaises(ValueError):
                make_html_block('<p ' + attr + '="2">A</p>')

    @staticmethod
    def frame(host='vkvideo.ru', query='oid=-123&id=456&hash=0123456789abcdef&hd=2', extra=''):
        return ('<iframe src="https://' + host + '/video_ext.php?' + query + '" '
                'width="853" height="480" allow="autoplay; encrypted-media; fullscreen; '
                'picture-in-picture; screen-wake-lock;" frameborder="0" allowfullscreen' + extra + '></iframe>')

    def test_exact_reviewed_vk_embed_is_preserved(self):
        for host in ('vk.com', 'vkvideo.ru'):
            self.exact(self.frame(host))
            self.exact(self.frame(host, 'oid=123&id=456&hash=0123456789abcdef&hd=4&autoplay=1'))

    def test_vk_embed_cannot_expand_hosts_features_or_attributes(self):
        base = self.frame()
        bad = (self.frame('example.test'), self.frame('vkvideo.ru.evil.test'),
               self.frame(extra=' onload="alert(1)"'), self.frame(extra=' sandbox="allow-scripts"'),
               base.replace('https://', 'http://'), base.replace('vkvideo.ru', 'user@vkvideo.ru'),
               base.replace('vkvideo.ru/', 'vkvideo.ru:443/'), base.replace('/video_ext.php?', '/video.php?'),
               base.replace('&hd=2', '&hd=2&hd=4'), base.replace('&hd=2', '&hd=3'),
               base.replace('&hd=2', '&hd=2&other=1'), base.replace('&hd=2', '&hd=2#x'),
               base.replace('hash=0123456789abcdef', 'hash=short'), base.replace('oid=-123', 'oid=0'),
               base.replace('id=456', 'id=-456'), base.replace('width="853"', 'width="100%"'),
               base.replace('height="480"', 'height="4097"'), base.replace('frameborder="0"', 'frameborder="1"'),
               base.replace('screen-wake-lock;', 'camera;'), base.replace(' allowfullscreen', ''),
               base.replace('allowfullscreen>', 'allowfullscreen="false">'))
        for markup in bad:
            with self.subTest(markup=markup), self.assertRaises(ValueError):
                make_html_block(markup)
        for attr in ('allow="fullscreen"', 'frameborder="0"', 'allowfullscreen'):
            with self.assertRaises(ValueError):
                make_html_block('<p ' + attr + '>A</p>')

    def test_existing_drive_embed_remains_exact_and_restricted(self):
        self.exact('<iframe src="https://drive.google.com/file/d/file123/preview" width="640" height="480"></iframe>')
        with self.assertRaises(ValueError):
            make_html_block('<iframe src="https://drive.google.com/file/d/file123/preview" width="640" height="480" allowfullscreen></iframe>')

    def test_exact_explicit_youtube_vk_group_keeps_both_players_and_captions(self):
        from lms.lms import avo_transform as transform
        root = {'name': 'page', 'children': [{'name': 'section', 'children': [
            {'name': 'column', 'children': [
                {'name': 'text', 'fields': {'html': '<p>Основной плеер</p>'}},
                {'name': 'video', 'fields': {'videoProvider': 'youtube', 'videoSrc': 'https://youtu.be/abcdefghijk'}}]},
            {'name': 'column', 'children': [
                {'name': 'text', 'fields': {'html': '<p>Альтернативный плеер</p>'}},
                {'name': 'text', 'fields': {'html': self.frame()}}]}]}]}
        original = copy.deepcopy(root)
        payload = {'account': 'mastervision', 'source_origin': 'https://shop.mastervision.su',
                   'course_id': 901, 'lesson_id': 902, 'course_title': 'Course',
                   'lesson_title': 'Lesson', 'format': 'ape', 'ape': root}
        self.assertIn('legacy_player_pair_unresolved', transform.plan_import(payload)['issues'])
        digest = hashlib.sha256(json.dumps(root, ensure_ascii=True, sort_keys=True,
                                          separators=(',', ':'), allow_nan=False).encode()).hexdigest()
        with patch.dict(transform.REVIEWED_VK_HTML_LABELS, {('mastervision', '901', '902'): digest}):
            plan = transform.plan_import(payload)
            self.assertTrue(plan['ready'], plan['issues'])
            self.assertEqual([b['type'] for b in plan['blocks']], ['paragraph', 'videoChoice', 'paragraph', 'htmlBlock'])
            self.assertEqual(base64.b64decode(plan['blocks'][-1]['data']['encodedHtml']).decode(), self.frame())
            root['children'][0]['children'][1]['children'][0]['fields']['html'] += ' Changed'
            self.assertIn('reviewed_source_changed', transform.plan_import(payload)['issues'])
        root['children'][0]['children'][1]['children'][0]['fields']['html'] = '<p>Альтернативный плеер</p>'
        self.assertEqual(root, original)


if __name__ == '__main__':
    unittest.main()

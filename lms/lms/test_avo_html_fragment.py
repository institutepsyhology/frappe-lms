import base64
import unittest
from lms.lms.avo_html_fragment import make_html_block


class StaticFragmentTests(unittest.TestCase):
    def test_preserves_reviewed_formatting_and_extension_attributes(self):
        html = ('<div class="lesson-mission-wrapper" style="margin: 0px 0px 10px; line-height: 1.1">'
                '<span class="redactor-inline-converted" style="background-color: transparent; font-weight: 700">'
                'Текст<br style="font-size: 16px"></span>'
                '<a href="https://example.test/material" style="text-decoration-line: none" '
                'savefrom_lm="1" savefrom_lm_index="0">Материал</a></div>')
        result = make_html_block(html)
        self.assertEqual(base64.b64decode(result['data']['encodedHtml']).decode('utf-8'), html)

    def test_preserves_static_layout_attributes(self):
        html = ('<div class="xdget-block row" data-xdget-id="123" id="block-123" '
                'style="position:relative; background-image:initial; min-height:1px">'
                '<p dir="ltr" style="white-space:pre-wrap; vertical-align:baseline">'
                '<a span="" href="https://example.test/material">Материал</a></p></div>')
        result = make_html_block(html)
        self.assertEqual(base64.b64decode(result['data']['encodedHtml']).decode('utf-8'), html)

    def test_preserves_html_without_interpretation(self):
        html='<div class="lesson-mission-wrapper" style="font-size: 16px"><h4><a href="https://example.test/a?x=1&amp;y=2" target="_blank">Материалы</a></h4><hr><ul><li>Текст</li></ul></div>'
        result=make_html_block(html)
        self.assertEqual(base64.b64decode(result['data']['encodedHtml']).decode('utf-8'),html)

    def test_rejects_active_and_unknown_html(self):
        for html in ('<script>alert(1)</script>','<iframe src="https://example.test"></iframe>',
                     '<a href="javascript:alert(1)">x</a>','<a href="https://example.test" onclick="alert(1)">x</a>',
                     '<div style="background:url(https://example.test)">x</div>',
                     '<form action="https://example.test"><input></form>',
                     '<a href="https://example.test" savefrom_lm="bad">x</a>',
                     '<a href="https://example.test" savefrom_lm_index="x">x</a>',
                     '<div savefrom_lm="1">x</div>',
                     '<p dir="javascript:bad">x</p>', '<div span="">x</div>',
                     '<div data-xdget-id="not-a-number">x</div>',
                     '<div style="position:fixed">x</div>',
                     '<div style="background-color:url(https://example.test)">x</div>',
                     '<div class="unreviewed">text</div>','<div><p>unbalanced</div>'):
            with self.assertRaises(ValueError):make_html_block(html)


if __name__=='__main__':unittest.main()

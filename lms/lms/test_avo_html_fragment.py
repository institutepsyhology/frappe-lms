import base64
import unittest
from lms.lms.avo_html_fragment import make_html_block


class StaticFragmentTests(unittest.TestCase):
    def test_preserves_html_without_interpretation(self):
        html='<div class="lesson-mission-wrapper" style="font-size: 16px"><h4><a href="https://example.test/a?x=1&amp;y=2" target="_blank">Материалы</a></h4><hr><ul><li>Текст</li></ul></div>'
        result=make_html_block(html)
        self.assertEqual(base64.b64decode(result['data']['encodedHtml']).decode('utf-8'),html)

    def test_rejects_active_and_unknown_html(self):
        for html in ('<script>alert(1)</script>','<iframe src="https://example.test"></iframe>',
                     '<a href="javascript:alert(1)">x</a>','<a href="https://example.test" onclick="alert(1)">x</a>',
                     '<div style="background:url(https://example.test)">x</div>',
                     '<form action="https://example.test"><input></form>',
                     '<div class="unreviewed">text</div>','<div><p>unbalanced</div>'):
            with self.assertRaises(ValueError):make_html_block(html)


if __name__=='__main__':unittest.main()

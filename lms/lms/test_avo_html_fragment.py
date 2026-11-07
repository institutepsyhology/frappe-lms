import base64
import unittest
from lms.lms.avo_html_fragment import make_html_block, strip_empty_answer_form, replace_drive_audio, strip_obsolete_manager_paragraphs


class StaticFragmentTests(unittest.TestCase):
    def test_reviewed_list_styles_preserve_markup_and_reject_active_values(self):
        html=('<ol><li style="list-style-type: decimal; font-variant-numeric: normal; '
              'font-variant-east-asian: normal; text-decoration-skip-ink: none">Задание</li></ol>')
        self.assertEqual(base64.b64decode(make_html_block(html)['data']['encodedHtml']).decode(),html)
        for bad in (html.replace('decimal','url(https://bad.test)'),html.replace('normal','expression(alert(1))',1)):
            with self.assertRaises(ValueError):make_html_block(bad)
        headings='<h5 id="h.example123">Урок</h5><ol start="4"><li aria-level="1">Пункт</li></ol>'
        self.assertEqual(base64.b64decode(make_html_block(headings)['data']['encodedHtml']).decode(),headings)
        for bad in (headings.replace('start="4"','start="4 onload=alert(1)"'),headings.replace('aria-level="1"','aria-level="0"')):
            with self.assertRaises(ValueError):make_html_block(bad)
        extra='<p style="font-variant-ligatures: normal; text-decoration-style: initial; text-decoration-color: initial">Текст</p>'
        self.assertEqual(base64.b64decode(make_html_block(extra)['data']['encodedHtml']).decode(),extra)
        self.assertEqual(base64.b64decode(make_html_block('<font face="Arial">Текст</font>')['data']['encodedHtml']).decode(),'<font face="Arial">Текст</font>')
        with self.assertRaises(ValueError):make_html_block('<font face="Arial;url(bad)">Текст</font>')

    def test_remove_only_obsolete_manager_paragraphs(self):
        before='<p>Содержание курса</p>'
        old='<p><b>Для приобретения&nbsp; данного пакета обучения,&nbsp; обратитесь к менеджеру по оплате.</b></p>'
        old+='<p>Это можно сделать прямо из вашего личного кабинета через мессенджер (кнопки для связи в правом нижнем углу: чат и телеграмм).</p>'
        after='<p>Дополнительный материал</p>'
        self.assertEqual(strip_obsolete_manager_paragraphs(before+old+after),before+after)
        with self.assertRaises(ValueError):strip_obsolete_manager_paragraphs(before+old.replace('менеджеру','куратору')+after)
        with self.assertRaises(ValueError):strip_obsolete_manager_paragraphs(before+old+old+after)
    def test_timing_tables_preserve_rows_and_reject_unsafe_attributes(self):
        html=('<table width="336" style="border-collapse: collapse"><colgroup><col width="65"><col width="271"></colgroup>'
              '<tbody><tr><td style="border-top: 1px solid #000000; overflow-wrap: break-word">02:25</td>'
              '<td><span style="font-variant: normal; font-style: normal; text-decoration: none">Тема</span></td></tr></tbody></table>')
        self.assertEqual(base64.b64decode(make_html_block(html)['data']['encodedHtml']).decode(),html)
        for bad in (html.replace('width="336"','width="1 onload=alert(1)"'),
                    html.replace('<td>','<td onclick="alert(1)">'),
                    html.replace('break-word','url(https://bad.test)'),
                    html.replace('</tbody>','<script>alert(1)</script></tbody>')):
            with self.assertRaises(ValueError):make_html_block(bad)
    def test_static_float_layout_preserves_html(self):
        html='<div class="col-md-12" style="float: left; width: 862.444px">Текст</div>'
        self.assertEqual(base64.b64decode(make_html_block(html)['data']['encodedHtml']).decode(),html)
        for bad in ('float: url(https://bad.test)','float: expression(alert(1))','float: arbitrary'):
            with self.assertRaises(ValueError):make_html_block('<div style="'+bad+'">x</div>')

    def test_reviewed_inert_layout_and_outline(self):
        source='<div class="o-lt-video lt-video gc-main-content xdget-root"><a style="outline: 0px" href="https://example.test">x</a></div>'
        self.assertEqual(base64.b64decode(make_html_block(source)['data']['encodedHtml']).decode(),source)
        with self.assertRaises(ValueError):make_html_block(source.replace('outline: 0px','outline: url(https://bad.test)'))

    def test_google_drive_image_preview_and_audio_link(self):
        iframe='<iframe height="480" src="https://drive.google.com/file/d/abc_DEF-123/preview" width="640"></iframe>'
        fragment='<p>Картинка</p>'+iframe+'<p>Задание</p>'
        self.assertEqual(base64.b64decode(make_html_block(fragment)['data']['encodedHtml']).decode(),fragment)
        audio='<audio controls="" controlslist="nodownload"><source src="https://drive.google.com/uc?export=view&amp;id=abc_DEF-123" /></audio>'
        transformed=replace_drive_audio('<p>'+audio+'</p>')
        self.assertIn('https://drive.google.com/file/d/abc_DEF-123/view',transformed)
        self.assertNotIn('<audio',transformed)
        make_html_block(transformed)
        for bad in (iframe.replace('drive.google.com','example.test'),iframe.replace('/preview','/edit'),
                    iframe.replace('width="640"','onload="alert(1)"'),
                    audio.replace('drive.google.com','example.test'),audio+'<audio>unknown</audio>'):
            with self.assertRaises(ValueError):
                replace_drive_audio(bad) if '<audio' in bad else make_html_block(bad)
        self.assertEqual(replace_drive_audio(audio+audio).count('АУДИОЗАПИСЬ'),2)
        self.assertIn('АУДИОЗАПИСЬ',replace_drive_audio(audio.replace('nodownload"','nodownload" title="hello world"')))
        with self.assertRaises(ValueError):replace_drive_audio(audio.replace('nodownload"','nodownload" onclick="alert(1)"'))

    def test_preserves_only_known_safe_clipboard_stylesheet(self):
        html = ('<p style="text-align: center"><style type="text/css">'
                '<!--td {border: 1px solid #ccc;}br {mso-data-placement:same-cell;}-->'
                '</style><strong>Текст</strong></p>')
        result=make_html_block(html)
        self.assertEqual(base64.b64decode(result['data']['encodedHtml']).decode(),html)
        for bad in (html.replace('#ccc','url(https://bad.test)'),
                    html.replace('text/css','text/javascript'),
                    html.replace('text-align: center','text-align: expression(alert(1))')):
            with self.assertRaises(ValueError):make_html_block(bad)

    def test_only_empty_answer_form_is_removed_without_touching_task_text(self):
        html = ('<div class="lesson-mission-wrapper"><div class="lesson-mission-text">Задание {name}</div>'
                '<div class="lesson-send-answer-block"><form action="/answer" method="post" '
                'enctype="multipart/form-data"><div class="answer-form"><div class="answer-form-content">'
                '<div><div class="answer-textarea-container"></div></div></div></div></form></div></div>')
        result = strip_empty_answer_form(html)
        self.assertIn('Задание {name}',result)
        self.assertNotIn('<form',result)
        make_html_block(result)
        for bad in (html.replace('</form>','Личный ответ</form>'),
                    html.replace('</form>','<input value="private"></form>'),
                    html+html):
            with self.assertRaises(ValueError):strip_empty_answer_form(bad)

    def test_single_empty_answer_form_is_removed_without_touching_text(self):
        html='<p>Текст задания</p><form action="/answer" method="post" enctype="multipart/form-data"><div class="answer-form">&nbsp;</div></form><p>Материалы</p>'
        self.assertEqual(strip_empty_answer_form(html),'<p>Текст задания</p><p>Материалы</p>')
        with self.assertRaises(ValueError):strip_empty_answer_form(html.replace('&nbsp;','Ответ ученика'))

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

    def test_preserves_font_colour_and_only_empty_answers_placeholder(self):
        html = ('<div class="xdget-lessonAnswers" data-xdget-id="123" id="answers">'
                '<div class="row"><div class="col-md-12"> </div></div></div>'
                '<p><font color="#3984c6">Текст</font></p>')
        result = make_html_block(html)
        self.assertEqual(base64.b64decode(result['data']['encodedHtml']).decode('utf-8'), html)
        for html in ('<div class="xdget-lessonAnswers">Личный ответ</div>',
                     '<div class="xdget-lessonAnswers"><a href="https://example.test">x</a></div>',
                     '<font color="javascript:alert(1)">x</font>'):
            with self.assertRaises(ValueError):make_html_block(html)

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

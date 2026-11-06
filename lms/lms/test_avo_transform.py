import unittest
from lms.lms.avo_transform import plan_import


def sample(content, fmt="preview"):
    result = {"account": "mv-centr", "course_id": 5, "lesson_id": 13,
              "course_title": "Курс", "lesson_title": "Урок", "format": fmt}
    result["content" if fmt == "preview" else "ape"] = content
    return result


class TransformTests(unittest.TestCase):
    def test_heading_preserves_formatted_link_and_long_text(self):
        text='А'*450+' <span style="color: red"><a href="https://example.test" target="_blank"><b>ссылка</b></a></span>'
        root={'name':'page','children':[{'name':'header','fields':{'html':'<h5>'+text+'</h5>','format':'h5'}}]}
        result=plan_import(sample(root,'ape'))
        self.assertTrue(result['ready'],result['issues'])
        self.assertEqual(result['blocks'][0]['data'],{'text':text,'level':5})
        root['children'][0]['fields']['html']='<h5><a href="javascript:alert(1)">x</a></h5>'
        self.assertIn('unsupported_header',plan_import(sample(root,'ape'))['issues'])
        root['children'][0]['fields']['html']='<h5><img src="https://example.test/x" /></h5>'
        self.assertIn('unsupported_header',plan_import(sample(root,'ape'))['issues'])

    def test_avo_titles_support_512_characters(self):
        p=sample({'name':'page','children':[{'name':'text','fields':{'html':'<p>OK</p>'}}]},'ape')
        p['course_title']='А'*512;p['lesson_title']='Б'*512
        self.assertTrue(plan_import(p)['ready'])
        p['course_title']='А'*513
        with self.assertRaisesRegex(ValueError,'invalid_title'):plan_import(p)

    def test_owner_omits_only_exact_trainer_header(self):
        import hashlib
        from unittest.mock import patch
        from lms.lms import avo_transform as module
        header='<h2><a target="_blank" href="https://example.test/question"><b>Задать вопрос тренеру</b></a></h2>'
        node={'name':'header','fields':{'html':header,'format':'h1'}}
        p=sample({'name':'page','children':[{'name':'text','fields':{'html':'<p>Содержание</p>'}},node]},'ape');p.update(course_id=447,lesson_id=2608)
        with patch.dict(module.CONFIRMED_OMIT_HEADERS,{('mv-centr','447','2608'):hashlib.sha256(header.encode()).hexdigest()}):
            out=plan_import(p);self.assertTrue(out['ready'],out['issues'])
            self.assertEqual(len(out['blocks']),1);self.assertIn('owner_omitted_trainer_link',out['warnings'])
            node['fields']['html']=header.replace('тренеру','преподавателю')
            changed=plan_import(p)
            self.assertNotIn('owner_omitted_trainer_link',changed['warnings'])
            self.assertEqual(changed['blocks'][-1]['type'],'header')

    def test_exact_placeholder_greeting_is_omitted_without_changing_snapshot(self):
        import hashlib,copy
        from unittest.mock import patch
        from lms.lms import avo_transform as module
        url='https://example.test/unnamed.jpeg'
        section={'name':'section','children':[{'name':'column','children':[{'name':'image','id':'one','fields':{'imageSrc':url}}]},
            {'name':'column','children':[{'name':'text','fields':{'html':'<p>Здравствуйте, {name}</p>'}}]}]}
        p=sample({'name':'page','children':[section,{'name':'text','fields':{'html':'<p>Keep</p>'}}]},'ape');p.update(course_id=258,lesson_id=1151)
        original=copy.deepcopy(p)
        with patch.object(module,'PLACEHOLDER_IMAGE_SHA256',hashlib.sha256(url.encode()).hexdigest()):
            out=plan_import(p);self.assertTrue(out['ready'],out['issues'])
            self.assertEqual([b['data']['text'] for b in out['blocks']],['<p>Keep</p>'])
            self.assertIn('owner_omitted_placeholder_greeting',out['warnings']);self.assertEqual(p,original)
            section['children'][1]['children'][0]['fields']['html']='<p>Здравствуйте, {name}! Важный текст</p>'
            self.assertIn('unsupported_multicolumn_layout',plan_import(p)['issues'])

    def test_standalone_placeholder_nodes_only_omit_exact_content(self):
        import hashlib
        from unittest.mock import patch
        from lms.lms import avo_transform as module
        url='https://example.test/unnamed.jpeg'
        nodes=[{'name':'image','fields':{'imageSrc':url}},{'name':'text','fields':{'html':'<p>Здравствуйте, {name}</p>'}},
               {'name':'text','fields':{'html':'<p>Keep</p>'}}]
        p=sample({'name':'page','children':nodes},'ape')
        with patch.object(module,'PLACEHOLDER_IMAGE_SHA256',hashlib.sha256(url.encode()).hexdigest()):
            out=plan_import(p);self.assertTrue(out['ready'],out['issues'])
            self.assertEqual(len(out['blocks']),1)
            nodes[1]['fields']['html']='<p>Здравствуйте, {name}! Important</p>'
            self.assertEqual(len(plan_import(p)['blocks']),2)

    def test_requested_html_field_preserves_original_markup(self):
        import base64,hashlib
        from unittest.mock import patch
        from lms.lms import avo_transform as module
        source='<p><strong>Материалы</strong></p>'
        p=sample({'name':'page','children':[{'name':'text','fields':{'html':source}}]},'ape')
        p.update(course_id=258,lesson_id=1151)
        with patch.dict(module.CONFIRMED_HTML_FIELDS,{('mv-centr','258','1151'):hashlib.sha256(source.encode()).hexdigest()}):
            out=plan_import(p)
            self.assertTrue(out['ready'],out['issues'])
            self.assertEqual(base64.b64decode(out['blocks'][0]['data']['encodedHtml']).decode(),source)
            p['account']='iomp'
            self.assertNotEqual(plan_import(p)['blocks'][0]['type'],'htmlBlock')

    def test_reviewed_lesson_spacer_uses_html_when_renderer_unavailable(self):
        import json,base64
        from pathlib import Path
        node=json.loads((Path(__file__).parent/'testdata/avo_spacer.json').read_text(encoding='utf-8'))
        p=sample({'name':'page','children':[node]},'ape');p.update(course_id=258,lesson_id=1150)
        out=plan_import(p);self.assertTrue(out['ready'],out['issues'])
        self.assertEqual(out['blocks'][0]['type'],'htmlBlock')
        self.assertIn('background-color:',base64.b64decode(out['blocks'][0]['data']['encodedHtml']).decode())
        self.assertIn('ape_spacer_frame_approximation',out['warnings'])
        p['course_id']=259
        self.assertEqual(plan_import(p)['blocks'][0]['type'],'lessonSpacer')

    def test_only_exact_confirmed_section_is_flattened(self):
        import hashlib,json
        from unittest.mock import patch
        from lms.lms import avo_transform as module
        section={'name':'section','fields':{'backgroundOverlayColor':{'enabled':False}},'children':[
            {'name':'column','children':[{'name':'text','fields':{'html':'<p>First</p>'}}]},
            {'name':'column','children':[{'name':'text','fields':{'html':'<p>Second</p>'}}]}]}
        p=sample({'name':'page','children':[section]},'ape');p.update(course_id=258,lesson_id=1150)
        digest=hashlib.sha256(json.dumps(section,ensure_ascii=True,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()
        with patch.dict(module.CONFIRMED_SINGLE_COLUMN_SECTIONS,{('mv-centr','258','1150'):digest}):
            out=plan_import(p);self.assertTrue(out['ready'],out['issues'])
            self.assertEqual([x['data']['text'] for x in out['blocks']],['<p>First</p>','<p>Second</p>'])
            section['children'][0]['children'][0]['fields']['html']='<p>Changed</p>'
            self.assertIn('unsupported_multicolumn_layout',plan_import(p)['issues'])
            p['account']='iomp'
            self.assertIn('unsupported_multicolumn_layout',plan_import(p)['issues'])

    def test_confirmed_audio_replacement_preserves_other_content_and_children(self):
        import base64, hashlib
        from unittest.mock import patch
        from lms.lms import avo_transform as module
        html=('<p><a href="https://example.test/first">First audio</a></p>'
              '<p><audio controls="" controlslist="nodownload"><source '
              'src="https://drive.google.com/uc?export=view&amp;id=abcdefgh" /></audio></p>')
        node={'name':'text','fields':{'html':html},'children':[{'name':'text','fields':{'html':'<p>Task</p>'}}]}
        p=sample({'name':'page','children':[node]},'ape');p.update(course_id=237,lesson_id=7315)
        with patch.dict(module.CONFIRMED_DRIVE_AUDIO_LINKS,{('mv-centr','237','7315'):hashlib.sha256(html.encode()).hexdigest()}):
            out=plan_import(p)
            self.assertTrue(out['ready'],out['issues'])
            rendered=''.join(b['data']['text'] if b['type']=='paragraph' else base64.b64decode(b['data']['encodedHtml']).decode() for b in out['blocks'][:-1])
            self.assertIn('https://example.test/first',rendered)
            self.assertIn('https://drive.google.com/file/d/abcdefgh/view',rendered)
            self.assertEqual(out['blocks'][-1]['data']['text'],'<p>Task</p>')
            self.assertEqual(node['fields']['html'],html)
            p['account']='iomp'
            self.assertFalse(plan_import(p)['ready'])
            p['account']='mv-centr';node['fields']['html']+='changed'
            self.assertFalse(plan_import(p)['ready'])

    def test_disabled_background_overlay_is_safe_but_enabled_is_not_ignored(self):
        overlay={'enabled':False,'r':255,'g':255,'b':255,'a':0.6}
        root={'name':'page','fields':{'backgroundOverlayColor':overlay},
              'children':[{'name':'text','fields':{'html':'<p>Текст</p>'}}]}
        out=plan_import(sample(root,'ape'))
        self.assertTrue(out['ready'],out['issues'])
        self.assertIn('ape_layout_settings_not_rendered',out['warnings'])
        overlay['enabled']=True
        self.assertIn('unsupported_background_overlay',plan_import(sample(root,'ape'))['issues'])
        overlay['enabled']=False;overlay['r']=999
        self.assertIn('unsupported_background_overlay',plan_import(sample(root,'ape'))['issues'])

    def test_owner_requested_flattening_applies_only_to_two_lessons(self):
        def column(title, youtube, rutube):
            return {'name':'column','children':[
                {'name':'text','fields':{'html':'<p>'+title+'</p>'}},
                {'name':'video','fields':{'videoProvider':'youtube','videoSrc':youtube,
                    'videoProvider2':'rutube','videoSrc2':rutube}}]}
        a='https://youtu.be/abcdefghijk';b='https://youtu.be/zzzzzzzzzzz'
        r='https://rutube.ru/video/0123456789abcdef0123456789abcdef/'
        root={'name':'page','children':[{'name':'section','children':[column('Первое',a,r),column('Второе',b,r)]}]}
        for course,lesson in ((117,571),(118,587)):
            p=sample(root,'ape');p.update(course_id=course,lesson_id=lesson)
            out=plan_import(p)
            self.assertTrue(out['ready'],out['issues'])
            self.assertEqual([x['type'] for x in out['blocks']],['paragraph','videoChoice','paragraph','videoChoice'])
            self.assertEqual([x['data']['youtube'] for x in out['blocks'] if x['type']=='videoChoice'],[a,b])
            self.assertIn('user_requested_single_column',out['warnings'])
            p['account']='iomp'
            self.assertIn('unsupported_multicolumn_layout',plan_import(p)['issues'])
        p=sample(root,'ape');p.update(course_id=117,lesson_id=572)
        self.assertIn('unsupported_multicolumn_layout',plan_import(p)['issues'])

    def test_confirmed_empty_answer_form_is_omitted_but_source_and_task_survive(self):
        import base64, hashlib
        from unittest.mock import patch
        from lms.lms import avo_transform as module
        html = ('<div class="lesson-mission-wrapper"><div class="lesson-mission-text">Задание {name}</div>'
                '<div class="lesson-send-answer-block"><form action="/answer" method="post" enctype="multipart/form-data">'
                '<div class="answer-form"><div class="answer-form-content"><div><div class="answer-textarea-container">'
                '</div></div></div></div></form></div></div>')
        root={'name':'page','children':[{'name':'text','fields':{'html':html}}]}
        payload=sample(root,'ape');payload.update(course_id=25,lesson_id=115)
        digest=hashlib.sha256(html.encode()).hexdigest()
        with patch.dict(module.CONFIRMED_TEXT_ONLY_ANSWER_FORMS,{('mv-centr','25','115'):digest}):
            out=plan_import(payload)
            self.assertTrue(out['ready'],out['issues'])
            rendered=base64.b64decode(out['blocks'][0]['data']['encodedHtml']).decode()
            self.assertIn('Задание {name}',rendered)
            self.assertNotIn('<form',rendered)
            self.assertEqual(root['children'][0]['fields']['html'],html)
            self.assertIn('answer_form_omitted_at_user_request',out['warnings'])
            payload['account']='iomp'
            self.assertFalse(plan_import(payload)['ready'])

    def test_confirmed_concatenated_video_uses_only_second_without_changing_source(self):
        import hashlib
        from unittest.mock import patch
        first = 'https://youtu.be/abcdefghijk'
        second = 'https://youtu.be/zzzzzzzzzzz'
        combined = first + second
        node = {'name':'video','fields':{'videoProvider':'youtube','videoSrc':combined}}
        payload = sample({'name':'page','children':[node]},'ape')
        payload.update(course_id=19,lesson_id=62)
        digest = hashlib.sha256(combined.encode()).hexdigest()
        from lms.lms import avo_transform as module
        with patch.dict(module.CONFIRMED_CONCATENATED_YOUTUBE, {('mv-centr','19','62'):digest}):
            out = plan_import(payload)
            self.assertTrue(out['ready'], out['issues'])
            self.assertEqual(out['blocks'][0]['data']['youtube'], second)
            self.assertIn('user_selected_second_youtube',out['warnings'])
            self.assertEqual(node['fields']['videoSrc'], combined)
            payload['account'] = 'iomp'
            self.assertFalse(plan_import(payload)['ready'])
            payload['account'] = 'mv-centr'
            node['fields']['videoSrc'] = first + 'https://youtu.be/xxxxxxxxxxx'
            self.assertFalse(plan_import(payload)['ready'])

    def test_identical_video_slots_are_one_video_but_different_links_stop(self):
        url = 'https://youtu.be/abcdefghijk'
        fields = {'videoProvider':'youtube','videoSrc':url,'videoProvider2':'youtube','videoSrc2':url}
        out = plan_import(sample({'name':'page','children':[{'name':'video','fields':fields}]},'ape'))
        self.assertTrue(out['ready'], out['issues'])
        self.assertEqual(len(out['blocks']), 1)
        self.assertEqual(out['blocks'][0]['data']['youtube'], url)
        self.assertEqual(out['blocks'][0]['data']['rutube'], '')
        self.assertIn('duplicate_video_sources_combined', out['warnings'])
        fields['videoSrc2'] = 'https://youtu.be/zzzzzzzzzzz'
        out = plan_import(sample({'name':'page','children':[{'name':'video','fields':fields}]},'ape'))
        self.assertFalse(out['ready'])
        self.assertIn('video_pair_unsupported', out['issues'])

    def test_multicolumn_content_is_not_flattened_into_a_ready_import(self):
        root = {'name': 'page', 'children': [{'name': 'section', 'children': [
            {'name': 'column', 'children': [{'name': 'text', 'fields': {'html': '<p>Левая</p>'}}]},
            {'name': 'column', 'children': [{'name': 'text', 'fields': {'html': '<p>Правая</p>'}}]},
        ]}]}
        out = plan_import(sample(root, 'ape'))
        self.assertFalse(out['ready'])
        self.assertIn('unsupported_multicolumn_layout', out['issues'])

    def test_spacer_preserves_dimensions_colour_and_rejects_unknown_variants(self):
        import copy, json
        from pathlib import Path
        node = json.loads((Path(__file__).parent / 'testdata/avo_spacer.json').read_text(encoding='utf-8'))
        root = {'name': 'page', 'children': [node]}
        out = plan_import(sample(root, 'ape'))
        self.assertTrue(out['ready'], out['issues'])
        self.assertEqual(out['blocks'], [{'type': 'lessonSpacer', 'data': {
            'height': 6, 'width': 100, 'marginTop': 10, 'marginBottom': 10, 'color': '#c8c8c8'}}])
        changed = copy.deepcopy(node)
        changed['style']['lists']['$__max_width__767__spacer']['height']['value']['number'] = 40
        self.assertFalse(plan_import(sample({'name':'page','children':[changed]},'ape'))['ready'])
        changed = copy.deepcopy(node)
        changed['style']['lists']['spacer']['backgroundImage']['value']['url'] = 'https://example.test/image.png'
        self.assertFalse(plan_import(sample({'name':'page','children':[changed]},'ape'))['ready'])

    def test_ape_header_keeps_visible_level_and_warns_if_setting_differs(self):
        root={'name':'page','children':[{'name':'header','fields':{'anchor':'','format':'h1','html':'<h2>Занятие <strong>1</strong></h2>'}}]}
        out=plan_import(sample(root,'ape'))
        self.assertTrue(out['ready'],out['issues'])
        self.assertEqual(out['blocks'][0],{'type':'header','data':{'text':'Занятие <strong>1</strong>','level':2}})
        self.assertIn('ape_heading_format_mismatch',out['warnings'])

    def test_ape_header_rejects_unrecognized_or_active_markup(self):
        for fields in ({'format':'h1','anchor':'name','html':'<h2>text</h2>'},
                       {'format':'h1','anchor':'','html':'<h2><script>alert(1)</script></h2>'},
                       {'format':'h1','anchor':'','html':'<h2><p>nested</p></h2>'},
                       {'format':'h1','anchor':'','html':'<h2>one</h2><h2>two</h2>'}):
            out=plan_import(sample({'name':'page','children':[{'name':'header','fields':fields}]},'ape'))
            self.assertFalse(out['ready'])

    def test_static_html_fragment_keeps_original_bytes_and_links(self):
        import base64
        html=('<div class="lesson-mission-wrapper" style="font-size: 14px"><h4><strong>'
              '<a href="https://example.test/one?a=1&amp;b=2" target="_blank">АНКЕТА</a>'
              '</strong></h4><hr><ul><li>До слова плату</li></ul></div>')
        out=plan_import(sample({'name':'page','children':[{'name':'text','fields':{'html':html}}]},'ape'))
        self.assertTrue(out['ready'],out['issues'])
        self.assertEqual(out['blocks'][0]['type'],'htmlBlock')
        self.assertEqual(base64.b64decode(out['blocks'][0]['data']['encodedHtml']).decode('utf-8'),html)
        self.assertIn('ape_static_html_frame_unverified',out['warnings'])

    def test_html_fallback_does_not_execute_active_content(self):
        for html in ('<div><script>alert(1)</script></div>',
                     '<div><a href="javascript:alert(1)">bad</a></div>',
                     '<form action="https://example.test"><input name="x"></form>',
                     '<div style="background:url(https://example.test)">x</div>'):
            out=plan_import(sample({'name':'page','children':[{'name':'text','fields':{'html':html}}]},'ape'))
            self.assertFalse(out['ready'])

    def test_multiple_labelled_pairs_with_empty_second_provider_slot(self):
        def text(value):return {'name':'text','fields':{'html':'<p>'+value+'</p>'}}
        def video(provider,url):return {'name':'video','fields':{'videoProvider':provider,'videoSrc':url,'videoProvider2':'rutube','videoSrc2':''}}
        sections=[]
        for _ in range(10):
            sections.append({'name':'section','children':[
                {'name':'column','children':[text('ОСНОВНОЙ ПЛЕЕР'),video('youtube','https://youtu.be/abcdefghijk')]},
                {'name':'column','children':[text('АЛЬТЕРНАТИВНЫЙ ПЛЕЕР'),video('rutube','https://rutube.ru/video/0123456789abcdef0123456789abcdef/')]},
            ]})
        out=plan_import(sample({'name':'page','children':sections},'ape'))
        self.assertTrue(out['ready'],out['issues'])
        self.assertEqual(sum(x['type']=='videoChoice' for x in out['blocks']),10)
        sections[0]['children'][1]['children'][1]['fields']['videoProvider2']='unrecognized'
        self.assertFalse(plan_import(sample({'name':'page','children':sections},'ape'))['ready'])

    def test_larger_payload_keeps_a_finite_complexity_limit(self):
        from lms.lms import avo_transform as transform
        transform._bounded({'data':[0]*60000})
        with self.assertRaisesRegex(ValueError,'input_structure_limit'):
            transform._bounded({'data':[0]*200001})

    def test_trim_surrounding_space_in_source_link_and_warn(self):
        root={'name':'page','children':[{'name':'text','fields':{'html':'<p><a href=" https://example.test/file ">Материал</a></p>'}}]}
        out=plan_import(sample(root,'ape'))
        self.assertTrue(out['ready'],out['issues'])
        self.assertIn('ape_text_formatting_not_reconstructed',out['warnings'])
        self.assertIn('href="https://example.test/file"',out['blocks'][0]['data']['text'])
        root['children'][0]['fields']['html']='<a href=" javascript:alert(1) ">bad</a>'
        self.assertFalse(plan_import(sample(root,'ape'))['ready'])

    def test_video_wrapper_preserves_separate_links_without_css(self):
        html=('<div class="video_wrapper" style="text-align:center"><a href="https://example.test/a" target="_blank">Первый</a></div>'
              '<div class="video_wrapper" style="text-align:center"><a href="https://example.test/b">Второй</a></div>')
        out=plan_import(sample({'name':'page','children':[{'name':'text','fields':{'html':html}}]},'ape'))
        self.assertTrue(out['ready'],out['issues'])
        text=out['blocks'][0]['data']['text']
        self.assertEqual(text,'<p><a href="https://example.test/a">Первый</a></p><p><a href="https://example.test/b">Второй</a></p>')
        self.assertIn('ape_text_formatting_not_reconstructed',out['warnings'])

    def test_unrecognized_wrapper_or_active_link_is_rejected(self):
        for html in ('<div class="unknown"><a href="https://example.test">x</a></div>',
                     '<div class="video_wrapper"><p>x</p></div>',
                     '<a href="https://example.test" target="evil">x</a>',
                     '<div class="video_wrapper" onclick="alert(1)">x</div>'):
            out=plan_import(sample({'name':'page','children':[{'name':'text','fields':{'html':html}}]},'ape'))
            self.assertFalse(out['ready'])

    def test_ape_link_style_is_removed_but_href_and_text_survive(self):
        root={'name':'page','children':[{'name':'text','fields':{'html':'<p><a style="color:red" href="https://example.test/file?a=1&amp;b=2">Материал</a></p>'}}]}
        out=plan_import(sample(root,'ape'))
        self.assertTrue(out['ready'],out['issues'])
        self.assertIn('ape_text_formatting_not_reconstructed',out['warnings'])
        text=out['blocks'][0]['data']['text']
        self.assertIn('href="https://example.test/file?a=1&amp;b=2"',text)
        self.assertIn('Материал',text)
        self.assertNotIn('style=',text)

    def test_ape_link_active_attributes_and_unsafe_urls_rejected(self):
        for bad in ('<a href="javascript:alert(1)" style="color:red">link</a>',
                    '<a href="https://example.test" onclick="alert(1)" style="color:red">link</a>',
                    '<a href="https://example.test" href="https://example.test/other" style="color:red">link</a>'):
            out=plan_import(sample({'name':'page','children':[{'name':'text','fields':{'html':bad}}]},'ape'))
            self.assertFalse(out['ready'])
            self.assertIn('unsafe_or_unrecognized_html',out['issues'])

    def test_labelled_legacy_players_become_one_pair_for_each_account(self):
        def text_block(value):
            return {'name': 'text', 'fields': {'html': '<p><strong>' + value + '</strong></p>'}}
        def video(provider, url):
            return {'name': 'video', 'fields': {'videoProvider': provider, 'videoSrc': url}}
        yt = 'https://youtu.be/abcdefghijk'
        rt = 'https://rutube.ru/play/embed/0123456789abcdef0123456789abcdef/?p=secret'
        root = {'name':'page','children':[{'name':'section','children':[{'name':'column','children':[
            text_block('До видео'), text_block('ОСНОВНОЙ ПЛЕЕР'), video('youtube', yt),
            text_block('АЛЬТЕРНАТИВНЫЙ ПЛЕЕР'), video('rutube', rt), text_block('После видео')
        ]}]}]}
        for account in ('iomp', 'mv-centr', 'mastervision'):
            payload = sample(root, 'ape'); payload['account'] = account
            out = plan_import(payload)
            self.assertTrue(out['ready'], out['issues'])
            self.assertEqual([x['type'] for x in out['blocks']], ['paragraph','videoChoice','paragraph'])
            self.assertEqual(out['blocks'][1]['data'], {'youtube':yt,'rutube':rt,'defaultProvider':'youtube'})
            self.assertIn('legacy_player_labels_combined', out['warnings'])

    def test_do_not_guess_pairs_for_different_labels_or_intervening_content(self):
        def text_block(value): return {'name':'text','fields':{'html':'<p>' + value + '</p>'}}
        def video(provider, code): return {'name':'video','fields':{'videoProvider':provider,'videoSrc':code}}
        yt = video('youtube','https://youtu.be/abcdefghijk')
        rt = video('rutube','https://rutube.ru/play/embed/0123456789abcdef0123456789abcdef/')
        for nodes in (
            [text_block('ОСНОВНОЙ ПЛЕЕР'), yt, text_block('Другая часть'), rt],
            [text_block('ОСНОВНОЙ ПЛЕЕР'), yt, text_block('АЛЬТЕРНАТИВНЫЙ ПЛЕЕР'), text_block('Текст'), rt],
            [text_block('ОСНОВНОЙ ПЛЕЕР'), yt, text_block('АЛЬТЕРНАТИВНЫЙ ПЛЕЕР'), yt],
            [text_block('ОСНОВНОЙ ПЛЕЕР ЧАСТЬ 1'), yt, text_block('АЛЬТЕРНАТИВНЫЙ ПЛЕЕР ЧАСТЬ 1'), rt],
        ):
            out = plan_import(sample({'name':'page','children':nodes}, 'ape'))
            self.assertFalse(out['ready'])
            self.assertIn('legacy_player_pair_unresolved', out['issues'])
            self.assertEqual(sum(b['type']=='videoChoice' for b in out['blocks']), 2)
            self.assertNotIn('legacy_player_labels_combined', out['warnings'])

        split = {'name':'page', 'children':[
            {'name':'section','children':[text_block('ОСНОВНОЙ ПЛЕЕР'),yt]},
            {'name':'section','children':[text_block('АЛЬТЕРНАТИВНЫЙ ПЛЕЕР'),rt]},
        ]}
        out = plan_import(sample(split, 'ape'))
        self.assertFalse(out['ready'])
        self.assertIn('legacy_player_pair_unresolved', out['issues'])

    def test_many_pairs_keep_both_sources_order_and_default(self):
        nodes = []
        for index in range(20):
            first, second = (('youtube', 'rutube') if index % 2 == 0 else ('rutube', 'youtube'))
            urls = {'youtube': 'https://youtu.be/abcdefghijk',
                    'rutube': 'https://rutube.ru/play/embed/0123456789abcdef0123456789abcdef/?p=secret'}
            nodes.extend([
                {'name':'text','fields':{'html':'<p>ОСНОВНОЙ ПЛЕЕР</p>'}},
                {'name':'video','fields':{'videoProvider':first,'videoSrc':urls[first]}},
                {'name':'text','fields':{'html':'<p>АЛЬТЕРНАТИВНЫЙ ПЛЕЕР</p>'}},
                {'name':'video','fields':{'videoProvider':second,'videoSrc':urls[second]}},
            ])
        out = plan_import(sample({'name':'page','children':nodes}, 'ape'))
        self.assertTrue(out['ready'], out['issues'])
        self.assertEqual(len(out['blocks']), 20)
        self.assertEqual([b['data']['defaultProvider'] for b in out['blocks']],
                         ['youtube', 'rutube'] * 10)
        self.assertTrue(all(b['data']['youtube'] and b['data']['rutube'].endswith('?p=secret')
                            for b in out['blocks']))

    def test_ape_independent_videos_buttons_image_and_formatted_text(self):
        image_id = '83d9d865-1b9e-4086-a355-bb6f68be4730'
        root = {'name': 'page', 'children': [
            {'name': 'image', 'id': image_id, 'fields': {'imageSrc': 'https://example.test/img.jpg', 'anchor': ''}},
            {'name': 'text', 'fields': {'html': '<p style="text-align:center"><span style="color:red"><strong>Здравствуйте, {name}</strong></span></p>', 'anchor': ''}},
            {'name': 'video', 'fields': {'videoProvider': 'youtube', 'videoSrc': 'https://youtu.be/abcdefghijk'}},
            {'name': 'text', 'fields': {'html': '<p>Другой проигрыватель</p>'}},
            {'name': 'video', 'fields': {'videoProvider': 'rutube', 'videoSrc': 'https://rutube.ru/play/embed/0123456789abcdef0123456789abcdef/?p=secret'}},
            {'name': 'button', 'fields': {'html': 'Аудио', 'url': 'https://example.test/audio', 'linkType': 'url', 'blank': True, 'anchor': '', 'toAnchor': '', 'event': '', 'icon': ''}},
        ]}
        out = plan_import(sample(root, 'ape'), {image_id: '/private/files/image.jpg'})
        self.assertTrue(out['ready'], out['issues'])
        self.assertEqual([b['type'] for b in out['blocks']], ['image', 'paragraph', 'videoChoice', 'paragraph', 'videoChoice', 'paragraph'])
        self.assertIn('{name}', out['blocks'][1]['data']['text'])
        self.assertIn('ape_text_formatting_not_reconstructed', out['warnings'])
        self.assertEqual(out['blocks'][2]['data']['youtube'], 'https://youtu.be/abcdefghijk')
        self.assertEqual(out['blocks'][2]['data']['rutube'], '')
        self.assertEqual(out['blocks'][4]['data']['youtube'], '')
        self.assertIn('?p=secret', out['blocks'][4]['data']['rutube'])
        self.assertIn('https://example.test/audio', out['blocks'][5]['data']['text'])
        self.assertIn('image_not_prepared', plan_import(sample(root, 'ape'))['issues'])

    def test_ape_formatted_html_and_button_refuse_unrecognized_data(self):
        for node in [
            {'name': 'text', 'fields': {'html': '<p><script>alert(1)</script></p>'}},
            {'name': 'text', 'fields': {'html': '<span onclick="alert(1)">x</span>'}},
            {'name': 'button', 'fields': {'html': 'x', 'url': 'javascript:alert(1)', 'linkType': 'url'}},
            {'name': 'button', 'fields': {'html': 'x', 'url': 'https://example.test', 'linkType': 'event', 'event': 'doSomething'}},
            {'name': 'button', 'fields': {'html': '<strong>Audio</strong>', 'url': 'https://example.test', 'linkType': 'url'}},
        ]:
            self.assertFalse(plan_import(sample({'name':'page','children':[node]}, 'ape'))['ready'])

    def test_pair_text_links_and_original_query(self):
        youtube = "https://youtu.be/abcdefghijk"
        rutube = "https://rutube.ru/video/private/0123456789abcdef0123456789abcdef/?p=secret&x=1"
        payload = sample([
            {"type": "video_pair", "players": [{"provider": "youtube", "url": youtube},
                                              {"provider": "rutube", "url": rutube}]},
            {"type": "text", "text": "Здравствуйте, {name}\nследующая строка"},
            {"type": "links", "items": [{"label": "План & текст", "url": "https://example.test/a?p=1&x=2"}]},
        ])
        plan = plan_import(payload)
        self.assertTrue(plan["ready"])
        self.assertIn("video_player_may_drop_parameters", plan["warnings"])
        self.assertEqual(plan["blocks"][0]["data"]["rutube"], rutube)
        self.assertEqual(plan["blocks"][0]["data"]["youtube"], youtube)
        self.assertIn("{name}<br>", plan["blocks"][1]["data"]["text"])
        self.assertIn("&amp;", plan["blocks"][2]["data"]["text"])

    def test_unknown_missing_and_same_provider_refuse(self):
        for item in [
            {"type": "video_pair", "players": []},
            {"type": "video_pair", "players": [{"provider": "youtube", "url": "https://youtu.be/abc"},
                                              {"provider": "youtube", "url": "https://youtu.be/def"}]},
            {"type": "text", "html": '<iframe src="https://example.test/"></iframe>'},
            {"type": "unknown"},
        ]:
            self.assertFalse(plan_import(sample([item]))["ready"])

    def test_ape_traversal_and_html(self):
        root = {"name": "page", "fields": {}, "children": [
            {"name": "text", "fields": {"html": '<p>Привет, {name}! <a href="https://example.test/?x=1&amp;y=2">Материал</a></p>'}},
            {"name": "video", "fields": {"videoProvider": "youtube", "videoSrc": "https://youtu.be/abcdefghijk",
             "videoProvider2": "rutube", "videoSrc2": "https://rutube.ru/video/private/0123456789abcdef0123456789abcdef/?p=1"}}]}
        out = plan_import(sample(root, "ape"))
        self.assertTrue(out["ready"])
        self.assertEqual([x["type"] for x in out["blocks"]], ["paragraph", "videoChoice"])
        self.assertIn("{name}", out["blocks"][0]["data"]["text"])

    def test_image_requires_prepared_private_file(self):
        src = sample([{"type": "image", "image_key": "slide1", "caption": "Схема"}])
        self.assertIn("image_not_prepared", plan_import(src)["issues"])
        self.assertFalse(plan_import(src, {"slide1": "/private/files/../bad.png"})["ready"])
        plan = plan_import(src, {"slide1": "/private/files/import-123.png"})
        self.assertTrue(plan["ready"])
        self.assertEqual(plan["blocks"][0]["data"]["url"], "/private/files/import-123.png")

    def test_reject_invalid_values(self):
        x = sample([])
        x["course_id"] = True
        with self.assertRaises(ValueError):
            plan_import(x)

    def test_incomplete_and_order_are_not_silent(self):
        self.assertIn("empty_lesson", plan_import(sample({"name": "page", "children": []}, "ape"))["issues"])
        x = sample([{"type": "text", "text": "second", "order": 2},
                    {"type": "text", "text": "first", "order": 1}])
        self.assertIn("ambiguous_block_order", plan_import(x)["issues"])
        x = sample({"name": "page", "children": [{"name": "text", "fields": {"html": "Text", "other": "lost"}}]}, "ape")
        self.assertIn("unsupported_text_settings", plan_import(x)["issues"])
        x = sample([{"type": "text", "html": '<a href="https://example.test/ bad">x</a>'}])
        self.assertFalse(plan_import(x)["ready"])
        self.assertIn("invalid_block", plan_import(sample([{"type": []}]))["issues"])
        self.assertIn("unknown_preview_fields", plan_import(sample([{"type": "text", "text": "x", "extra": "not rendered"}]))["issues"])
        x = sample([{"type": "text", "html": '<a href="javascript:alert(1)">x</a>'}])
        self.assertFalse(plan_import(x)["ready"])
        x = sample([])
        x["account"] = "other/../account"
        with self.assertRaises(ValueError):
            plan_import(x)


if __name__ == "__main__":
    unittest.main()

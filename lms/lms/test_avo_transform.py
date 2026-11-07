import unittest
from lms.lms.avo_transform import plan_import


def sample(content, fmt="preview"):
    result = {"account": "mv-centr", "course_id": 5, "lesson_id": 13,
              "course_title": "Курс", "lesson_title": "Урок", "format": fmt}
    result["content" if fmt == "preview" else "ape"] = content
    return result


class TransformTests(unittest.TestCase):
    def test_simple_header_preserves_safe_formatting_and_rejects_active_content(self):
        root={'name':'page','children':[{'name':'header-simple','fields':{'level':'h4','html':'<strong>Практикум</strong>'}}]}
        result=plan_import(sample(root,'ape'))
        self.assertTrue(result['ready'],result['issues'])
        self.assertEqual(result['blocks'][0],{'type':'header','data':{'text':'<strong>Практикум</strong>','level':4}})
        root['children'][0]['fields']['html']='<script>alert(1)</script>'
        self.assertFalse(plan_import(sample(root,'ape'))['ready'])

    def test_reviewed_remote_image_set_keeps_both_images_and_captions(self):
        import base64,hashlib
        from unittest.mock import patch
        from lms.lms import avo_transform as module
        tags=['<img src="https://i.mycdn.me/image?id=1" />','<img src="https://i.mycdn.me/image?id=2" />']
        html='<p>Ответ 1 '+tags[0]+'</p><p>Ответ 2 '+tags[1]+'</p>'
        root={'name':'page','children':[{'name':'text','fields':{'html':html}}]}
        rule=(hashlib.sha256(html.encode()).hexdigest(),tuple(hashlib.sha256(x.encode()).hexdigest() for x in tags))
        with patch.dict(module.REVIEWED_REMOTE_IMAGE_SETS,{('mv-centr','5','13'):rule}):
            result=plan_import(sample(root,'ape'))
            self.assertTrue(result['ready'],result['issues'])
            self.assertEqual(base64.b64decode(result['blocks'][0]['data']['encodedHtml']).decode(),html)
            root['children'][0]['fields']['html']=html.replace('id=2','id=3')
            self.assertFalse(plan_import(sample(root,'ape'))['ready'])

    def test_owner_omits_empty_audio_only_for_exact_reviewed_source(self):
        import hashlib,json
        from unittest.mock import patch
        from lms.lms import avo_transform as module
        root={'name':'page','children':[{'name':'text','fields':{'html':'<p>Материал</p>'}},
            {'name':'button','fields':{'linkType':'url','html':'АУДИОЗАПИСЬ','url':''}}]}
        digest=hashlib.sha256(json.dumps(root,ensure_ascii=True,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()
        with patch.dict(module.CONFIRMED_OMIT_EMPTY_BUTTONS,{('mv-centr','5','13'):digest}):
            result=plan_import(sample(root,'ape'))
            self.assertTrue(result['ready'],result['issues'])
            self.assertIn('Материал',str(result['blocks']))
            self.assertIn('user_omitted_empty_button',result['warnings'])
            root['children'][0]['fields']['html']='<p>Изменённый материал</p>'
            self.assertIn('reviewed_source_changed',plan_import(sample(root,'ape'))['issues'])

    def test_reviewed_remote_image_keeps_html_and_rejects_unreviewed_changes(self):
        import base64,hashlib
        from unittest.mock import patch
        from lms.lms import avo_transform as module
        tag='<img alt="" src="https://example.test/picture.jpg" />'
        html='<p>Задание</p><p>'+tag+'</p>'
        root={'name':'page','children':[{'name':'text','fields':{'html':html}}]}
        with patch.dict(module.REVIEWED_REMOTE_IMAGES,{('mv-centr','5','13'):(hashlib.sha256(html.encode()).hexdigest(),tag)}):
            result=plan_import(sample(root,'ape'))
            self.assertTrue(result['ready'],result['issues'])
            self.assertEqual(base64.b64decode(result['blocks'][0]['data']['encodedHtml']).decode(),html)
            root['children'][0]['fields']['html']=html.replace('picture.jpg','other.jpg')
            self.assertFalse(plan_import(sample(root,'ape'))['ready'])

    def test_vimeo_video_is_reported_instead_of_transferred(self):
        root={'name':'page','children':[{'name':'video','fields':{'videoProvider':'vimeo','videoSrc':'https://vimeo.com/488989277'}}]}
        result=plan_import(sample(root,'ape'))
        self.assertFalse(result['ready'])
        self.assertIn('vimeo_video_unavailable',result['issues'])
        self.assertNotIn('embed',[b['type'] for b in result['blocks']])
        root={'name':'page','children':[{'name':'text','fields':{'html':'<p><a href="https://vimeo.com/123">Видео</a></p>'}}]}
        self.assertIn('vimeo_video_unavailable',plan_import(sample(root,'ape'))['issues'])

    def test_owner_approved_placeholder_does_not_import_old_vimeo(self):
        import hashlib,json
        from unittest.mock import patch
        from lms.lms import avo_transform as module
        root={'name':'page','children':[{'name':'video','fields':{'videoProvider':'vimeo','videoSrc':'https://vimeo.com/123'}}]}
        digest=hashlib.sha256(json.dumps(root,ensure_ascii=True,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()
        with patch.dict(module.REVIEWED_SELECTIONS,{('mv-centr','5','13'):(digest,'placeholder',0)}):
            result=plan_import(sample(root,'ape'))
            self.assertTrue(result['ready'],result['issues'])
            self.assertNotIn('vimeo.com',str(result['blocks']))

    def test_reviewed_youtube_typo_keeps_rutube_pair(self):
        import hashlib
        from unittest.mock import patch
        from lms.lms import avo_transform as module
        broken='https:/youtu.be/6mqNJuP-uuw';good='https://youtu.be/6mqNJuP-uuw'
        root={'name':'page','children':[{'name':'video','fields':{'videoProvider':'youtube','videoSrc':broken,'videoProvider2':'rutube','videoSrc2':'https://rutube.ru/video/0123456789abcdef0123456789abcdef/'}}]}
        with patch.dict(module.REVIEWED_YOUTUBE_URLS,{('mv-centr','5','13'):(hashlib.sha256(broken.encode()).hexdigest(),good)}):
            result=plan_import(sample(root,'ape'))
            self.assertTrue(result['ready'],result['issues'])
            self.assertEqual(result['blocks'][0]['data']['youtube'],good)
            self.assertTrue(result['blocks'][0]['data']['rutube'])
            root['children'][0]['fields']['videoSrc']=broken+'x'
            self.assertFalse(plan_import(sample(root,'ape'))['ready'])

    def test_reviewed_material_links_preserve_all_eight_and_reject_unlinked_text(self):
        import hashlib
        from unittest.mock import patch
        from lms.lms import avo_transform as module
        html='<div>'+''.join('<p><a href="https://example.test/'+str(i)+'">Материал '+str(i)+'</a></p>' for i in range(8))+'</div>'
        root={'name':'page','children':[{'name':'text','fields':{'html':html}}]}
        with patch.dict(module.REVIEWED_LINK_LISTS,{('mv-centr','5','13'):hashlib.sha256(html.encode()).hexdigest()}):
            result=plan_import(sample(root,'ape'))
            self.assertTrue(result['ready'],result['issues'])
            self.assertEqual(len(result['blocks']),8)
            self.assertIn('example.test/7',str(result['blocks'][-1]))
            root['children'][0]['fields']['html']=html+'<p>Дополнительный текст</p>'
            changed=plan_import(sample(root,'ape'))
            self.assertNotIn('reviewed_material_links_extracted',changed['warnings'])
            if changed['ready']:
                import base64
                rendered=''.join(base64.b64decode(b['data']['encodedHtml']).decode() if b['type']=='htmlBlock' else b['data'].get('text','') for b in changed['blocks'])
                self.assertIn('Дополнительный текст',rendered)

    def test_reviewed_embedded_jpeg_keeps_complete_html_and_rejects_changes(self):
        import base64,hashlib
        from unittest.mock import patch
        from lms.lms import avo_transform as module
        raw=b'\xff\xd8\xffreviewed-image\xff\xd9'
        image=base64.b64encode(raw).decode()
        html='<p>Задание</p><p><img data-filename="screen.jpg" style="box-sizing: border-box; border: 0px; vertical-align: middle; max-width: 100%; width: 604px;" src="data:image/jpeg;base64,'+image+'" /></p>'
        root={'name':'page','children':[{'name':'text','fields':{'html':html}}]}
        with patch.dict(module.REVIEWED_EMBEDDED_JPEG,{('mv-centr','5','13'):hashlib.sha256(html.encode()).hexdigest()}),patch.object(module,'REVIEWED_JPEG_SHA256',hashlib.sha256(raw).hexdigest()):
            result=plan_import(sample(root,'ape'))
            self.assertTrue(result['ready'],result['issues'])
            self.assertEqual(base64.b64decode(result['blocks'][0]['data']['encodedHtml']).decode(),html)
            root['children'][0]['fields']['html']=html+'<script>alert(1)</script>'
            self.assertFalse(plan_import(sample(root,'ape'))['ready'])

    def test_reviewed_youtube_embeds_and_adjacent_html_preserve_order(self):
        import hashlib,base64
        from unittest.mock import patch
        from lms.lms import avo_transform as module
        iframe='<iframe allow="accelerometer; autoplay; encrypted-media; gyroscope; picture-in-picture" allowfullscreen="" frameborder="0" height="315" src="https://www.youtube.com/embed/6mqNJuP-uuw" width="560"></iframe>'
        tail='<p>Полный текст задания</p>'
        html='<p>'+iframe+'</p>'+tail
        root={'name':'page','children':[{'name':'text','fields':{'html':html}}]}
        with patch.dict(module.REVIEWED_MIXED_YOUTUBE,{('mv-centr','5','13'):(hashlib.sha256(html.encode()).hexdigest(),1)}):
            result=plan_import(sample(root,'ape'))
            self.assertTrue(result['ready'],result['issues'])
            self.assertEqual([b['type'] for b in result['blocks']],['videoChoice','htmlBlock'])
            self.assertEqual(base64.b64decode(result['blocks'][1]['data']['encodedHtml']).decode(),tail)
            root['children'][0]['fields']['html']=html.replace('Полный','Изменённый')
            self.assertFalse(plan_import(sample(root,'ape'))['ready'])

    def test_reviewed_youtube_iframes_remain_five_separate_videos(self):
        import hashlib
        from unittest.mock import patch
        from lms.lms import avo_transform as module
        ids=['6mqNJuP-uuw','s0crnbKYQa4','jPjMD0ag-hI','V7mbYkbdDNk','D_2I-zv4UuI']
        html='\n'.join('<iframe width="560" height="315" src="https://www.youtube.com/embed/'+i+'" frameborder="0" allow="accelerometer; autoplay; encrypted-media; gyroscope; picture-in-picture" allowfullscreen></iframe>' for i in ids)
        root={'name':'page','children':[{'name':'text','fields':{'html':html}}]}
        with patch.dict(module.REVIEWED_YOUTUBE_IFRAMES,{('mv-centr','5','13'):(hashlib.sha256(html.encode()).hexdigest(),5)}):
            result=plan_import(sample(root,'ape'))
            self.assertTrue(result['ready'],result['issues'])
            self.assertEqual([b['data']['youtube'].rsplit('/',1)[-1] for b in result['blocks']],ids)
            root['children'][0]['fields']['html']=html+'<p>Не пропускать</p>'
            self.assertFalse(plan_import(sample(root,'ape'))['ready'])

    def test_reviewed_single_youtube_iframe_is_scoped_and_complete(self):
        import hashlib
        from unittest.mock import patch
        from lms.lms import avo_transform as module
        html='<iframe width="560" height="315" src="https://www.youtube.com/embed/6mqNJuP-uuw" frameborder="0" allow="accelerometer; autoplay; encrypted-media; gyroscope; picture-in-picture" allowfullscreen></iframe>'
        root={'name':'page','children':[{'name':'text','fields':{'html':html}}]}
        key=('mv-centr','5','13')
        with patch.dict(module.REVIEWED_YOUTUBE_IFRAMES,{key:(hashlib.sha256(html.encode()).hexdigest(),1)}):
            result=plan_import(sample(root,'ape'))
            self.assertTrue(result['ready'],result['issues'])
            self.assertEqual(len(result['blocks']),1)
            self.assertTrue(result['blocks'][0]['data']['youtube'].endswith('6mqNJuP-uuw'))
            root['children'][0]['fields']['html'] += html
            self.assertFalse(plan_import(sample(root,'ape'))['ready'])

    def test_reviewed_centered_youtube_iframe_requires_exact_source(self):
        import hashlib
        from unittest.mock import patch
        from lms.lms import avo_transform as module
        html='<div class="center"><iframe width="630" height="360" src="https://www.youtube.com/embed/6mqNJuP-uuw" frameborder="0" allowfullscreen=""></iframe></div>'
        root={'name':'page','children':[{'name':'text','fields':{'html':html}}]}
        with patch.dict(module.REVIEWED_CENTERED_YOUTUBE_IFRAMES,{('mv-centr','5','13'):hashlib.sha256(html.encode()).hexdigest()}):
            result=plan_import(sample(root,'ape'))
            self.assertTrue(result['ready'],result['issues'])
            self.assertEqual(len(result['blocks']),1)
            self.assertTrue(result['blocks'][0]['data']['youtube'].endswith('6mqNJuP-uuw'))
            root['children'][0]['fields']['html'] += '<p>Не пропускать</p>'
            self.assertFalse(plan_import(sample(root,'ape'))['ready'])

    def test_empty_editor_blocks_are_ignored_without_dropping_content(self):
        root={'name':'page','children':[
            {'name':'header','fields':{'anchor':'','html':'','format':'h1'}},
            {'name':'code','fields':{'anchor':'','html':''}},
            {'name':'text','fields':{'html':'<p>Материал</p>'}}]}
        result=plan_import(sample(root,'ape'))
        self.assertTrue(result['ready'],result['issues'])
        self.assertEqual(len(result['blocks']),1)
        self.assertIn('Материал',str(result['blocks']))
        root['children'][1]['fields']['html']='<script>content</script>'
        self.assertFalse(plan_import(sample(root,'ape'))['ready'])
        root['children'][1]['fields']['html']=''
        root['children'][1]['children']=None
        self.assertFalse(plan_import(sample(root,'ape'))['ready'])

    def test_reviewed_formatted_button_keeps_text_and_destination(self):
        import hashlib
        from unittest.mock import patch
        from lms.lms import avo_transform as module
        label='<strong><span style="color: red">Материал</span></strong>'
        root={'name':'page','children':[{'name':'button','fields':{'html':label,'linkType':'url','url':'https://example.test/file'}}]}
        with patch.dict(module.REVIEWED_BUTTON_LABELS,{('mv-centr','5','13'):hashlib.sha256(label.encode()).hexdigest()}):
            result=plan_import(sample(root,'ape'))
            self.assertTrue(result['ready'],result['issues'])
            self.assertIn('example.test/file',str(result['blocks']))
            self.assertIn('<strong>Материал</strong>',str(result['blocks']))
            root['children'][0]['fields']['html']=label.replace('Материал','Другой')
            self.assertFalse(plan_import(sample(root,'ape'))['ready'])

    def test_static_list_in_header_is_preserved_as_html(self):
        import base64
        html='<ul><li style="text-align: left;"><h3>Первая тема</h3></li><li><h3>Вторая тема</h3></li></ul>'
        root={'name':'page','children':[{'name':'header','fields':{'html':html,'format':'h1'}}]}
        result=plan_import(sample(root,'ape'))
        self.assertTrue(result['ready'],result['issues'])
        block=result['blocks'][0]
        self.assertEqual(base64.b64decode(block['data']['encodedHtml']).decode(),html)
        self.assertGreaterEqual(block['data']['height'],180)
        root['children'][0]['fields']['html']='<ul><li><script>alert(1)</script></li></ul>'
        self.assertFalse(plan_import(sample(root,'ape'))['ready'])
        root['children'][0]['fields']['html']='<ul><li><a href="https://example.test">Материал</a></li></ul>'
        self.assertFalse(plan_import(sample(root,'ape'))['ready'])

    def test_reviewed_duplicate_vk_editor_field_preserves_visible_alternative(self):
        import hashlib,json
        from unittest.mock import patch
        from lms.lms import avo_transform as module
        iframe='<iframe src="https://vkvideo.ru/video_ext.php?oid=-1&amp;id=2&amp;hash=abc" width="1280" height="720"></iframe>'
        root={'name':'page','children':[
            {'name':'text','fields':{'html':'<p>Плеер 1</p>'}},
            {'name':'video','fields':{'videoProvider':'youtube','videoSrc':'https://youtu.be/6mqNJuP-uuw','videoProvider2':'embedded','videoSrc2':'','embeddedHtml2':iframe}},
            {'name':'text','fields':{'html':'<p>Плеер 2</p>'}},
            {'name':'video','fields':{'videoProvider':'embedded','videoProvider2':'rutube','videoSrc2':'','embeddedHtml':iframe}},
            {'name':'text','fields':{'html':'<p>Материалы</p>'}}]}
        digest=hashlib.sha256(json.dumps(root,ensure_ascii=True,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()
        payload=sample(root,'ape');payload.update(course_id=177,lesson_id=710)
        with patch.dict(module.CONFIRMED_VK_ALTERNATIVE,{('mv-centr','177','710'):(digest,hashlib.sha256(iframe.encode()).hexdigest())}):
            result=plan_import(payload)
            self.assertTrue(result['ready'],result['issues'])
            self.assertEqual([x['type'] for x in result['blocks']],['paragraph','videoChoice','paragraph','htmlBlock','paragraph'])
            root['children'][1]['fields']['embeddedHtml2']=iframe.replace('id=2','id=3')
            self.assertFalse(plan_import(payload)['ready'])

    def test_reviewed_google_link_typo_is_corrected_only_for_exact_source(self):
        import hashlib
        from unittest.mock import patch
        from lms.lms import avo_transform as module
        html='<p><a href="hhttps://drive.google.com/file/d/example/view">Материал</a></p>'
        root={'name':'page','children':[{'name':'text','fields':{'html':html}}]}
        with patch.dict(module.REVIEWED_LINK_TYPOS,{('mv-centr','5','13'):hashlib.sha256(html.encode()).hexdigest()}):
            result=plan_import(sample(root,'ape'))
            self.assertTrue(result['ready'],result['issues'])
            self.assertIn('https://drive.google.com/file/d/example/view',str(result['blocks']))
            self.assertEqual(root['children'][0]['fields']['html'],html)
            root['children'][0]['fields']['html']=html.replace('example','changed')
            self.assertFalse(plan_import(sample(root,'ape'))['ready'])

    def test_reviewed_numbered_vk_and_rutube_pairs_preserve_order(self):
        import hashlib,json
        from unittest.mock import patch
        from lms.lms import avo_transform as module
        iframe='<iframe src="https://vkvideo.ru/video_ext.php?oid=-1&amp;id=2&amp;hash=abc" width="1280" height="720"></iframe>'
        def text(value): return {'name':'text','fields':{'html':'<p>'+value+'</p>'}}
        def video(provider,url='',embedded=''):
            return {'name':'video','fields':{'videoProvider':provider,'videoSrc':url,'videoProvider2':'rutube','videoSrc2':'','embeddedHtml':embedded}}
        root={'name':'page','children':[
            text('Плеер 1'),video('youtube','https://youtu.be/6mqNJuP-uuw'),text('Плеер 2'),video('embedded',embedded=iframe),
            text('Плеер 1'),video('youtube','https://youtu.be/s0crnbKYQa4'),text('Плеер 2'),
            video('rutube','https://rutube.ru/video/0123456789abcdef0123456789abcdef/'),text('Материалы')]}
        digest=hashlib.sha256(json.dumps(root,ensure_ascii=True,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()
        payload=sample(root,'ape');payload.update(course_id=18,lesson_id=52)
        with patch.dict(module.CONFIRMED_VK_ALTERNATIVE,{('mv-centr','18','52'):(digest,hashlib.sha256(iframe.encode()).hexdigest())}):
            result=plan_import(payload)
            self.assertTrue(result['ready'],result['issues'])
            self.assertEqual([x['type'] for x in result['blocks']],['paragraph','videoChoice','paragraph','htmlBlock','videoChoice','paragraph'])
            self.assertTrue(result['blocks'][4]['data']['youtube'])
            self.assertTrue(result['blocks'][4]['data']['rutube'])
            root['children'].append(text('изменение'))
            self.assertIn('reviewed_source_changed',plan_import(payload)['issues'])

    def test_reviewed_styled_heading_keeps_html_and_rejects_changed_source(self):
        import hashlib,base64
        from unittest.mock import patch
        from lms.lms import avo_transform as module
        heading='<h2><strong><font color="#000000">Признаки</font></strong></h2>'
        root={'name':'page','children':[{'name':'header','fields':{'html':heading,'format':'h2'}}]}
        with patch.dict(module.REVIEWED_STYLED_HEADERS,{('mv-centr','5','13'):{hashlib.sha256(heading.encode()).hexdigest()}}):
            result=plan_import(sample(root,'ape'))
            self.assertTrue(result['ready'],result['issues'])
            self.assertEqual(base64.b64decode(result['blocks'][0]['data']['encodedHtml']).decode(),heading)
            root['children'][0]['fields']['html']=heading.replace('Признаки','Другое')
            self.assertFalse(plan_import(sample(root,'ape'))['ready'])

    def test_owner_removed_entire_obsolete_lesson_gets_neutral_placeholder(self):
        import hashlib,json
        from unittest.mock import patch
        from lms.lms import avo_transform as module
        root={'name':'page','children':[{'name':'text','fields':{'html':'<p>Устаревшее предложение</p>'}}]}
        digest=hashlib.sha256(json.dumps(root,ensure_ascii=True,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()
        p=sample(root,'ape')
        with patch.dict(module.REVIEWED_SELECTIONS,{('mv-centr','5','13'):(digest,'removed',0)}):
            result=plan_import(p)
            self.assertTrue(result['ready'],result['issues'])
            self.assertEqual(result['lesson_title'],'Урок в разработке')
            self.assertNotIn('Устаревшее предложение',str(result['blocks']))
            root['children'][0]['fields']['html']='<p>Изменено</p>'
            self.assertIn('reviewed_source_changed',plan_import(p)['issues'])
    def test_owner_excludes_trainer_links_across_block_types(self):
        root={'name':'page','children':[
            {'name':'text','fields':{'html':'<p>Материал <a href="https://example.test/file">Файл</a></p><p><a href="https://example.test/question"><b>Вопрос тренеру</b></a></p>'}},
            {'name':'button','fields':{'html':'ЗАДАТЬ ВОПРОС ТРЕНЕРУ','linkType':'url','url':'https://example.test/question'}},
            {'name':'button','fields':{'html':'Задать вопрос тренеру здесь','linkType':'url','url':'https://example.test/question'}},
            {'name':'header','fields':{'html':'<h2><a href="https://example.test/question">Задать вопрос тренеру</a></h2>','format':'h2'}},
            {'name':'button','fields':{'html':'Презентация','linkType':'url','url':'https://example.test/slides'}},
        ]}
        result=plan_import(sample(root,'ape'))
        self.assertTrue(result['ready'],result['issues'])
        self.assertIn('owner_omitted_trainer_link',result['warnings'])
        output=str(result['blocks'])
        self.assertNotIn('example.test/question',output)
        self.assertIn('example.test/file',output)
        self.assertIn('example.test/slides',output)

    def test_trainer_policy_preserves_unrelated_text_and_preview_links(self):
        p=sample([{'type':'text','order':1,'text':'Ваш тренер подготовил материал'},
                  {'type':'links','order':2,'items':[{'label':'Вопрос тренеру','url':'https://example.test/question'},
                                                      {'label':'Аудио','url':'https://example.test/audio'}]}])
        result=plan_import(p)
        self.assertTrue(result['ready'],result['issues'])
        self.assertIn('Ваш тренер подготовил материал',str(result['blocks']))
        self.assertNotIn('example.test/question',str(result['blocks']))
        self.assertIn('example.test/audio',str(result['blocks']))

    def test_trainer_link_removal_preserves_adjacent_content_and_rejects_broken_anchor(self):
        from lms.lms.avo_transform import _strip_trainer_links
        value='<p>До <a href="https://example.test/q"><strong>Задать&nbsp;вопрос тренеру</strong></a> после <a href="https://example.test/material">Материал</a></p>'
        cleaned, omitted=_strip_trainer_links(value)
        self.assertTrue(omitted)
        self.assertEqual(cleaned,'<p>До  после <a href="https://example.test/material">Материал</a></p>')
        with self.assertRaises(ValueError):
            _strip_trainer_links('<p><a href="https://example.test/q">Вопрос тренеру')

    def test_reviewed_html_removes_trainer_link_without_mutating_source(self):
        import base64,copy,hashlib
        from unittest.mock import patch
        from lms.lms import avo_transform as module
        text='<div><p>Задание</p><p><a href="https://example.test/trainer">Вопрос тренеру</a></p></div>'
        root={'name':'page','children':[{'name':'text','fields':{'html':text},'children':[]}]}
        p=sample(root,'ape');before=copy.deepcopy(p)
        with patch.dict(module.CONFIRMED_HTML_FIELDS,{('mv-centr','5','13'):hashlib.sha256(text.encode()).hexdigest()}):
            result=plan_import(p)
        self.assertTrue(result['ready'],result['issues'])
        html=base64.b64decode(result['blocks'][0]['data']['encodedHtml']).decode()
        self.assertIn('Задание',html)
        self.assertNotIn('example.test/trainer',html)
        self.assertEqual(p,before)

    def test_unrecognized_trainer_action_stops_instead_of_importing(self):
        root={'name':'page','children':[{'name':'button','fields':{'html':'Материалы и вопросы к тренеру','linkType':'url','url':'https://example.test/q'}}]}
        result=plan_import(sample(root,'ape'))
        self.assertFalse(result['ready'])
        self.assertIn('ambiguous_trainer_action',result['issues'])

    def test_trainer_link_removed_from_mixed_header(self):
        root={'name':'page','children':[{'name':'header','fields':{'html':'<h2>Тема <a href="https://example.test/q">Вопрос тренеру</a></h2>','format':'h2'}}]}
        result=plan_import(sample(root,'ape'))
        self.assertTrue(result['ready'],result['issues'])
        self.assertNotIn('example.test/q',str(result['blocks']))
        self.assertIn('Тема',str(result['blocks']))

    def test_legacy_audio_top_link_is_preserved_as_safe_link(self):
        html='<h4><strong><a target="_top" href="https://drive.google.com/file/d/example/view?usp=sharing">АУДИОЗАПИСЬ</a></strong></h4>'
        root={'name':'page','children':[{'name':'text','fields':{'html':html}}]}
        result=plan_import(sample(root,'ape'))
        self.assertTrue(result['ready'],result['issues'])
        self.assertIn('https://drive.google.com/file/d/example/view?usp=sharing',str(result['blocks']))
        self.assertIn('legacy_audio_link_normalized',result['warnings'])
        self.assertEqual(root['children'][0]['fields']['html'],html)
        root['children'][0]['fields']['html']=html.replace('https://drive.google.com/file/d/example/view?usp=sharing','javascript:alert(1)')
        self.assertFalse(plan_import(sample(root,'ape'))['ready'])

    def test_only_known_empty_video_overlay_is_omitted(self):
        overlay='<div class="video_wrapper" style="margin: 0 auto;position: relative"><div class="hov2" style=" height: 70px;position: absolute;top:0;left:0;right:0;width: 100%; z-index: 999;">&nbsp;</div></div>'
        root={'name':'page','children':[{'name':'text','fields':{'html':overlay+'<p>Задание</p>'}}]}
        result=plan_import(sample(root,'ape'))
        self.assertTrue(result['ready'],result['issues'])
        self.assertIn('Задание',str(result['blocks']))
        self.assertIn('empty_video_overlay_omitted',result['warnings'])
        root['children'][0]['fields']['html']=overlay.replace('&nbsp;','Содержимое')+'<p>Задание</p>'
        result=plan_import(sample(root,'ape'))
        self.assertFalse(result['ready'])
        inner=overlay.replace('&nbsp;</div></div>','&nbsp;</div><p>Заголовок</p></div>')
        root['children'][0]['fields']['html']=inner+'<p>Задание</p>'
        result=plan_import(sample(root,'ape'))
        self.assertTrue(result['ready'],result['issues'])
        self.assertEqual(result['blocks'][0]['type'],'htmlBlock')

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
            self.assertIn('<p>Здравствуйте, {name}! Важный текст</p>',
                          [b['data']['text'] for b in plan_import(p)['blocks']])

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

    def test_owner_selection_preserves_source_and_is_bound_to_account_and_capture(self):
        import copy, hashlib, json
        from unittest.mock import patch
        from lms.lms import avo_transform as module
        root={'name':'page','children':[
            {'name':'text','fields':{'html':'<p>Remove this</p>'}},
            {'name':'video','fields':{'videoProvider':'youtube','videoSrc':'https://youtu.be/abcdefghijk'}},
            {'name':'button','fields':{'linkType':'url','html':'Audio','url':'https://example.test/audio','blank':True}},
            {'name':'button','fields':{'linkType':'url','html':'Omit','url':'https://example.test/other'}}]}
        original=copy.deepcopy(root)
        digest=hashlib.sha256(json.dumps(root,ensure_ascii=True,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()
        p=sample(root,'ape');p.update(course_id=123,lesson_id=456)
        with patch.dict(module.REVIEWED_SELECTIONS,{('mv-centr','123','456'):(digest,'videos',1)}):
            out=plan_import(p)
            self.assertTrue(out['ready'],out['issues'])
            self.assertEqual([b['type'] for b in out['blocks']],['videoChoice','lessonButton'])
            self.assertEqual(out['blocks'][1]['data']['text'],'Audio')
            self.assertEqual(root,original)
            root['children'][0]['fields']['html']='<p>Changed</p>'
            self.assertIn('reviewed_source_changed',plan_import(p)['issues'])
            self.assertIsNone(module.reviewed_selection(original,'iomp',123,456))

    def test_owner_confirmed_vk_iframe_stays_after_youtube_and_is_hash_bound(self):
        import base64,hashlib,json
        from unittest.mock import patch
        from lms.lms import avo_transform as module
        iframe='<iframe src="https://vkvideo.ru/video_ext.php?oid=-1&id=1" width="1280" height="720"></iframe>'
        root={'name':'page','children':[{'name':'video','fields':{'videoProvider':'youtube','videoSrc':'https://youtu.be/abcdefghijk'}},
             {'name':'video','fields':{'videoProvider':'embedded','embeddedHtml':iframe}}]}
        digest=hashlib.sha256(json.dumps(root,ensure_ascii=True,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()
        rule=(digest,hashlib.sha256(iframe.encode()).hexdigest())
        p=sample(root,'ape');p.update(course_id=583,lesson_id=4086)
        with patch.dict(module.CONFIRMED_VK_ALTERNATIVE,{('mv-centr','583','4086'):rule}):
            out=plan_import(p);self.assertTrue(out['ready'],out['issues'])
            self.assertEqual([x['type'] for x in out['blocks']],['videoChoice','htmlBlock'])
            self.assertIn(iframe,base64.b64decode(out['blocks'][1]['data']['encodedHtml']).decode())
            root['children'][1]['fields']['embeddedHtml']=iframe.replace('id=1','id=2')
            self.assertIn('reviewed_source_changed',plan_import(p)['issues'])

    def test_button_whitespace_and_line_break_are_normalized_without_changing_source(self):
        import copy
        node={'name':'button','fields':{'linkType':'url','html':'Аудиозапись<br>',
             'url':' https://example.test/audio ', 'blank':True}}
        root={'name':'page','children':[node]}; original=copy.deepcopy(root)
        out=plan_import(sample(root,'ape'))
        self.assertTrue(out['ready'],out['issues'])
        self.assertEqual(out['blocks'][0]['data']['text'],
            '<a href="https://example.test/audio">Аудиозапись</a>')
        self.assertEqual(root,original)
        node['fields']['html']='<script>bad</script>'
        self.assertIn('unsupported_button',plan_import(sample(root,'ape'))['issues'])

    def test_owner_omits_only_empty_button_in_exact_reviewed_lesson(self):
        import copy,hashlib,json
        from unittest.mock import patch
        from lms.lms import avo_transform as module
        root={'name':'page','children':[{'name':'text','fields':{'html':'<p>Keep</p>'}},
             {'name':'button','fields':{'linkType':'url','html':'АУДИОЗАПИСЬ 2','url':''}},
             {'name':'button','fields':{'linkType':'url','html':'Other','url':'https://example.test/audio'}}]}
        original=copy.deepcopy(root)
        digest=hashlib.sha256(json.dumps(root,ensure_ascii=True,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()
        p=sample(root,'ape');p.update(course_id=952,lesson_id=9422)
        with patch.dict(module.CONFIRMED_OMIT_EMPTY_BUTTONS,{('mv-centr','952','9422'):digest}):
            out=plan_import(p)
            self.assertTrue(out['ready'],out['issues'])
            self.assertEqual(len(out['blocks']),2)
            self.assertIn('user_omitted_empty_button',out['warnings'])
            self.assertEqual(root,original)
            root['children'][0]['fields']['html']='<p>Changed</p>'
            self.assertIn('reviewed_source_changed',plan_import(p)['issues'])

    def test_spacer_is_omitted_even_for_previously_reviewed_lessons(self):
        import json
        from pathlib import Path
        node=json.loads((Path(__file__).parent/'testdata/avo_spacer.json').read_text(encoding='utf-8'))
        p=sample({'name':'page','children':[node,{'name':'text','fields':{'html':'<p>Содержание</p>'}}]},'ape');p.update(course_id=258,lesson_id=1150)
        out=plan_import(p);self.assertTrue(out['ready'],out['issues'])
        self.assertEqual([b['type'] for b in out['blocks']],['paragraph'])
        self.assertIn('user_omitted_separators',out['warnings'])
        p['course_id']=259
        self.assertEqual([b['type'] for b in plan_import(p)['blocks']],['paragraph'])

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
            self.assertEqual(plan_import(p)['blocks'][0]['data']['text'],'<p>Changed</p>')
            p['account']='iomp'
            self.assertTrue(plan_import(p)['ready'])

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
            self.assertTrue(plan_import(p)['ready'])
        p=sample(root,'ape');p.update(course_id=117,lesson_id=572)
        self.assertTrue(plan_import(p)['ready'])

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

    def test_multicolumn_content_is_flattened_in_source_order(self):
        root = {'name': 'page', 'children': [{'name': 'section', 'children': [
            {'name': 'column', 'children': [{'name': 'text', 'fields': {'html': '<p>Левая</p>'}}]},
            {'name': 'column', 'children': [{'name': 'text', 'fields': {'html': '<p>Правая</p>'}}]},
        ]}]}
        out = plan_import(sample(root, 'ape'))
        self.assertTrue(out['ready'],out['issues'])
        self.assertEqual([b['data']['text'] for b in out['blocks']],['<p>Левая</p>','<p>Правая</p>'])
        self.assertIn('user_requested_single_column', out['warnings'])

    def test_spacer_variants_are_ignored_but_empty_lesson_still_requires_review(self):
        import copy, json
        from pathlib import Path
        node = json.loads((Path(__file__).parent / 'testdata/avo_spacer.json').read_text(encoding='utf-8'))
        root = {'name': 'page', 'children': [node]}
        out = plan_import(sample(root, 'ape'))
        self.assertIn('empty_lesson', out['issues'])
        self.assertEqual(out['blocks'], [])
        changed = copy.deepcopy(node)
        changed['style']['lists']['$__max_width__767__spacer']['height']['value']['number'] = 40
        self.assertNotIn('unsupported_spacer',plan_import(sample({'name':'page','children':[changed]},'ape'))['issues'])
        changed = copy.deepcopy(node)
        changed['style']['lists']['spacer']['backgroundImage']['value']['url'] = 'https://example.test/image.png'
        self.assertNotIn('unsupported_spacer',plan_import(sample({'name':'page','children':[changed]},'ape'))['issues'])

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

"""Native metadata regressions model observed shapes, never private source text."""
import copy
import importlib.util
import json
from pathlib import Path
import unittest

from importer import Review
from normalize_editor_nodes import normalize_nodes

spec = importlib.util.spec_from_file_location('editor_test_static', Path(__file__).resolve().parents[2] / 'lms/lms/avo_html_fragment.py')
static = importlib.util.module_from_spec(spec); spec.loader.exec_module(static)
VALIDATE = static.make_html_block
YT = 'https://youtu.be/abcdefghijk'
RT = 'https://rutube.ru/video/private/0123456789abcdef0123456789abcdef/?p=private_key'
VIMEO = 'https://vimeo.com/123456789'


def page(*nodes): return {'name':'page','children':list(nodes)}


def video(provider='youtube',url=YT,**fields):
    return {'id':'video','name':'video','fields':{'videoProvider':provider,'videoSrc':url,**fields},'children':[]}


def heading(markup='<h2><b>Heading</b></h2>',format='h2',**fields):
    return {'id':'heading','name':'header','fields':{'html':markup,'format':format,**fields},'children':[]}


class EditorNodeTests(unittest.TestCase):
    def normalize(self,ape): return normalize_nodes(ape,VALIDATE)

    def test_already_importable_nodes_keep_exact_structure_and_fingerprint(self):
        ape=page(video(videoProvider2='rutube',videoSrc2=RT,html='Meaningful caption'),heading(),
            heading('<h3><strong>Format mismatch already supported</strong></h3>','h1'),
            {'name':'section','children':[{'name':'text','fields':{'html':'<p>Text {name}</p>'}}]})
        expected=json.dumps(ape,ensure_ascii=False,separators=(',',':'))
        out,changes=self.normalize(ape)
        self.assertEqual(changes,[])
        self.assertEqual(json.dumps(out,ensure_ascii=False,separators=(',',':')),expected)
        self.assertIsNot(out,ape);self.assertIsNot(out['children'][0],ape['children'][0])

    def test_observed_4932_stale_provider_labels_use_valid_rutube_urls(self):
        ape=page(*[video(provider,RT,html='Keep label',nativePlayer=False) for provider in ('youtube','vimeo','embedded','other')])
        original=copy.deepcopy(ape);out,changes=self.normalize(ape)
        self.assertEqual([node['fields']['videoProvider'] for node in out['children']],['rutube']*4)
        self.assertTrue(all(node['fields']['videoSrc']==RT for node in out['children']))
        self.assertTrue(all(node['fields']['html']=='Keep label' for node in out['children']))
        self.assertEqual(changes,[{'path':[i],'code':'native_video_provider_normalized'} for i in range(4)])
        self.assertEqual(ape,original)

    def test_pair_slots_order_urls_settings_and_labels_are_preserved(self):
        ape=page(video('youtube',RT,videoProvider2='rutube',videoSrc2=YT,html='Caption',
                       isShowProgressControl=True,posterSrc='https://example.test/poster.jpg',unknown={'keep':1}))
        out,changes=self.normalize(ape);fields=out['children'][0]['fields']
        self.assertEqual((fields['videoProvider'],fields['videoProvider2']),('rutube','youtube'))
        self.assertEqual((fields['videoSrc'],fields['videoSrc2']),(RT,YT))
        for key in ('html','isShowProgressControl','posterSrc','unknown'):
            self.assertEqual(fields[key],ape['children'][0]['fields'][key])
        self.assertEqual(len(changes),1)

    def test_genuine_vimeo_and_unvalidated_urls_are_never_repaired(self):
        for url in (VIMEO,'https://rutube.ru/video/private/0123456789abcdef0123456789abcdef/',
                    'https://youtube.com/watch?v=abcdefghijk&v=zyxwvutsrqp',YT+' ',
                    'https://example.test/video','http://rutube.ru/video/0123456789abcdef0123456789abcdef/'):
            ape=page(video('wrong',url));out,changes=self.normalize(ape)
            self.assertEqual(out,ape);self.assertEqual(changes,[])

    def test_observed_6519_to_6522_empty_native_video_keeps_remaining_content(self):
        empty=video(url='',nativePlayer=False,html='Видео',isShowProgressControl=True,
                    isShowFastRewindButtons=False,isFloating=False)
        empty['style']={'lists':{'content':'list-style formatting control'}}
        remaining=[{'name':'text','fields':{'html':'<p>Keep task</p>'}},
                   {'id':'picture','name':'image','fields':{'imageSrc':'https://example.test/image.png'}}]
        for _ in range(4):
            ape=page(empty,*remaining);out,changes=self.normalize(ape)
            self.assertEqual(out['children'],remaining)
            self.assertEqual(changes,[{'path':[0],'code':'empty_video_block_omitted'}])
            self.assertEqual(len(ape['children']),3)

    def test_empty_default_html_caption_and_original_child_paths(self):
        ape=page(video(url='',html='<p><b>Видео</b></p>'),
                 {'name':'column','children':[video(url='',html='<p><br></p>'),video()]})
        out,changes=self.normalize(ape)
        self.assertEqual([x['path'] for x in changes],[[0],[1,0]])
        self.assertEqual(out['children'][0]['children'],[video()])

    def test_empty_video_not_dropped_if_any_meaningful_content_or_unknown_field(self):
        candidates=[video(url='',html='Watch the next lesson'),video(url='',embeddedHtml='<iframe></iframe>'),
                    video(url='',posterSrc='https://example.test/poster.png'),video(url='',anchor='important'),
                    video(url='',fileId='unknown-media'),video(url='',newSetting=None),
                    video(url='',html='<p><a href="https://example.test/">Видео</a></p>'),
                    video(url='',html='<script>Видео</script>'),video(url='',videoProvider2='embedded')]
        for node in candidates:
            ape=page(node);out,changes=self.normalize(ape)
            self.assertEqual(out,ape);self.assertEqual(changes,[])

    def test_empty_video_preserves_children_and_style_images_or_text(self):
        for key,value in [('children',[{'name':'text','fields':{'html':'Keep'}}]),
                          ('style',{'backgroundImage':{'value':{'url':'https://example.test/image.png'}}}),
                          ('style',{'content':{'value':'meaningful caption'}})]:
            node=video(url='');node[key]=value;ape=page(node)
            out,changes=self.normalize(ape);self.assertEqual(out,ape);self.assertEqual(changes,[])

    def test_observed_2814_and_3395_mixed_headings_preserve_exact_html(self):
        for markup,format in [('<h2><b>First</b></h2>\n<h2><b>Second</b></h2>','h1'),
                              ('<h3><strong>First</strong></h3><h3><strong>Second</strong></h3>','h3')]:
            ape=page(heading(markup,format));out,changes=self.normalize(ape)
            result=out['children'][0]
            self.assertEqual(result['name'],'text');self.assertEqual(result['fields'],{'html':markup})
            self.assertEqual(result['id'],'heading');self.assertEqual(result['children'],[])
            self.assertEqual(changes,[{'path':[0],'code':'header_markup_preserved_as_text'}])

    def test_invalid_heading_format_with_static_heading_html_can_be_preserved(self):
        markup='<h2><strong>Preserve this heading</strong></h2>'
        out,changes=self.normalize(page(heading(markup,'not-a-heading')))
        self.assertEqual(out['children'][0]['fields']['html'],markup)
        self.assertNotIn('format',out['children'][0]['fields'])
        self.assertEqual(len(changes),1)

    def test_unknown_unsafe_or_non_heading_header_is_unchanged(self):
        candidates=[heading('<h2>Good</h2><script>bad()</script>','invalid'),
                    heading('<h2 onclick="bad()">Title</h2><h3>Other</h3>'),
                    heading('Plain text','invalid'),heading('<b>Normal inline</b>','h1'),
                    heading('<h2>A</h2><h2>B</h2>',anchor='keep'),
                    heading('<h2>A</h2><h2>B</h2>',unknown='keep')]
        for node in candidates:
            ape=page(node);out,changes=self.normalize(ape)
            self.assertEqual(out,ape);self.assertEqual(changes,[])

    def test_transformation_idempotent_and_metadata_contains_no_source(self):
        ape=page(video('vimeo',RT),video(url=''),heading('<h2>A</h2><h2>B</h2>','h1'))
        out,changes=self.normalize(ape);second,second_changes=self.normalize(out)
        self.assertEqual(second,out);self.assertEqual(second_changes,[])
        for item in changes:self.assertEqual(set(item),{'path','code'})
        self.assertNotIn('http',json.dumps(changes));self.assertNotIn('Caption',json.dumps(changes))

    def test_invalid_tree_or_validator_fail_with_fixed_review(self):
        for ape in ([],{'name':'text','children':[]},page({'name':'video','fields':[]}),page('unknown')):
            with self.assertRaises(Review):self.normalize(ape)
        with self.assertRaisesRegex(Review,'editor_nodes_validator_invalid'):normalize_nodes(page(),None)


if __name__=='__main__':unittest.main()

"""Native metadata regressions model observed shapes, never private source text."""
import copy
import importlib.util
import json
from pathlib import Path
import unittest

from importer import Review
from normalize_editor_nodes import normalize_nodes, _core

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


def simple_heading(markup='First<br>Second',level='h2',**fields):
    return {'id':'simple-heading','name':'header-simple',
            'fields':{'anchor':'','html':markup,'level':level,**fields},'children':[],
            'style':{'marginTop':{'value':'12px'}}}


def avatar(**fields):
    return {'id':'personal-avatar','name':'image',
            'fields':{'imageSrc':'{avatar_url}','anchor':'','linkHref':'',**fields},'children':[],
            'style':{'lists':{'block':{'display':'block'},'content':{'justifyContent':'center'},
                              'image':{'width':'100px','height':'auto','marginTop':'0px'}}}}


class EditorNodeTests(unittest.TestCase):
    def normalize(self,ape): return normalize_nodes(ape,VALIDATE)

    def test_simple_header_linebreak_keeps_exact_html_level_id_style_and_order(self):
        markup='First &amp; <strong>bold&nbsp;text</strong><br />\n<a href="https://example.test/file?x=1&amp;y=2">Notes</a><BR>Last'
        for level in ('h1','h2','h3','h4','h5','h6'):
            ape=page(video(),simple_heading(markup,level),{'name':'text','fields':{'html':'After'}})
            before=copy.deepcopy(ape);out,changes=self.normalize(ape)
            expected=copy.deepcopy(ape);node=expected['children'][1]
            node['name']='text';node['fields']['html']='<'+level+'>'+markup+'</'+level+'>';del node['fields']['level']
            self.assertEqual(out,expected);self.assertEqual(ape,before)
            self.assertEqual(changes,[{'path':[1],'code':'simple_header_linebreak_html_preserved'}])
            self.assertEqual(self.normalize(out),(out,[]));VALIDATE(out['children'][1]['fields']['html'])

    def test_simple_header_without_break_is_byte_identical(self):
        for markup in ('Native heading','<strong>Native</strong> &amp; text','<span style="color:red">Title</span>'):
            ape=page(simple_heading(markup));self.assertEqual(self.normalize(ape),(ape,[]))

    def test_simple_header_unsafe_attributes_block_tags_and_bad_breaks_are_retained(self):
        for markup in ('First<br class="text-left">Second','First<br style="color:red">Second',
                       'First<br onclick="private()">Second','First<br></br>Second',
                       '<p>First</p><br>Second','<h3>First</h3><br>Second',
                       '<ul><li>First</li></ul><br>Second','First<br><img src="https://example.test/a.png">',
                       'First<br><script>private()</script>','First<br><span onclick="private()">Second</span>',
                       '<strong>First<br>Second','First<!-- comment --><br>Second',
                       'First<br><a href="#local">Local</a>','<br>','&nbsp;<br>'):
            ape=page(simple_heading(markup));before=copy.deepcopy(ape)
            self.assertEqual(self.normalize(ape),(ape,[]));self.assertEqual(ape,before)

    def test_simple_header_strict_fields_children_style_and_conditions_are_protected(self):
        for fields in ({'anchor':'keep'},{'visibleConditions':None},{'visibleConditions':{'active':True}},
                       {'displayDelay':0},{'unknown':None}):
            ape=page(simple_heading(**fields));self.assertEqual(self.normalize(ape),(ape,[]))
        for level in ('h7','h2 ',None,2):
            ape=page(simple_heading(level=level));self.assertEqual(self.normalize(ape),(ape,[]))
        for key,value in (('children',[{'name':'text','fields':{'html':'Keep'}}]),
                          ('extra',None),('style',{'caption':'Keep'}),
                          ('style',{'backgroundImage':'https://example.test/image.png'})):
            node=simple_heading();node[key]=value;ape=page(node)
            self.assertEqual(self.normalize(ape),(ape,[]))
        for key in ('anchor','level'):
            node=simple_heading();del node['fields'][key];ape=page(node)
            self.assertEqual(self.normalize(ape),(ape,[]))
        ape={'name':'page','fields':{'visibleConditions':{'active':True}},'children':[simple_heading()]}
        self.assertEqual(self.normalize(ape),(ape,[]))

    def test_simple_header_source_and_wrapped_markup_must_both_validate(self):
        ape=page(simple_heading())
        def reject_wrapped(html):
            if html.startswith('<h2>'):raise ValueError('unsupported')
            return VALIDATE(html)
        self.assertEqual(normalize_nodes(ape,reject_wrapped),(ape,[]))
        self.assertEqual(normalize_nodes(ape,lambda _: (_ for _ in ()).throw(ValueError('unsupported'))),(ape,[]))

    def test_simple_header_real_core_preserves_break_heading_level_and_links(self):
        original={'account':'mastervision','source_origin':'https://shop.mastervision.su',
                  'course_id':7,'lesson_id':11,'course_title':'Synthetic','lesson_title':'Synthetic',
                  'format':'ape','ape':page(simple_heading('A<br><a href="https://example.test/file">B &amp; C</a>'))}
        self.assertIn('unsupported_header',_core().plan_import(original)['issues'])
        transformed=copy.deepcopy(original);transformed['ape'],_=self.normalize(original['ape'])
        plan=_core().plan_import(transformed)
        self.assertTrue(plan['ready']);self.assertEqual(plan['issues'],[])
        expected=copy.deepcopy(original);expected['ape']=page({'name':'text','fields':{
            'html':'<h2>A<br><a href="https://example.test/file">B &amp; C</a></h2>'}})
        self.assertEqual(plan['blocks'],_core().plan_import(expected)['blocks'])

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

    def test_personalized_avatar_omitted_while_all_real_image_settings_stay_exact(self):
        real={'id':'real-image','name':'image','fields':{
            'imageSrc':'https://f1.autoweboffice.com/example/school/real.png',
            'anchor':'','linkHref':'','displayDelay':'0','visibleConditions':[]},
            'style':{'lists':{'image':{'width':'80%','height':'auto'}}},'children':[]}
        other=copy.deepcopy(real);other['id']='other-image'
        other['fields']['imageSrc']='https://f1.autoweboffice.com/example/school/other.jpg'
        ape=page(avatar(),real,video(),{'name':'column','children':[other]});before=copy.deepcopy(ape)
        out,changes=self.normalize(ape)
        self.assertEqual(out['children'],[real,video(),{'name':'column','children':[other]}])
        self.assertEqual(json.dumps(out['children'][0]),json.dumps(real))
        self.assertEqual(json.dumps(out['children'][2]['children'][0]),json.dumps(other))
        self.assertEqual(changes,[{'path':[0],'code':'personalized_avatar_placeholder_omitted'}])
        self.assertEqual(ape,before)

    def test_avatar_minimal_missing_or_null_empty_fields_and_nested_original_paths(self):
        minimal={'name':'image','fields':{'imageSrc':'{avatar_url}'}}
        ape=page(avatar(anchor=None,linkHref=None),{'name':'column','children':[video(),minimal]})
        before=copy.deepcopy(ape);out,changes=self.normalize(ape)
        self.assertEqual(out['children'],[{'name':'column','children':[video()]}])
        self.assertEqual(changes,[{'path':[0],'code':'personalized_avatar_placeholder_omitted'},
                                  {'path':[1,1],'code':'personalized_avatar_placeholder_omitted'}])
        self.assertEqual(ape,before)
        second,second_changes=self.normalize(out)
        self.assertEqual(second,out);self.assertEqual(second_changes,[])

    def test_avatar_unknown_fields_macros_and_actual_missing_images_are_retained(self):
        nodes=[avatar(anchor='keep-anchor'),avatar(linkHref='https://example.test/material'),
               avatar(html='<p>Keep text</p>'),avatar(html=None),avatar(unknown=None),
               avatar(imageSrc='{other_url}'),avatar(imageSrc='{avatar_url} '),
               avatar(imageSrc=''),avatar(imageSrc=None),avatar(imageSrc='relative.png')]
        for node in nodes:
            ape=page(node);before=copy.deepcopy(ape)
            out,changes=self.normalize(ape)
            self.assertEqual(out,before);self.assertEqual(changes,[]);self.assertEqual(ape,before)

    def test_avatar_children_extra_node_fields_or_content_style_are_never_discarded(self):
        changes_to_try=[('children',[{'name':'text','fields':{'html':'<p>Keep</p>'}}]),
                        ('extra',None),('style',{'caption':'Meaningful text'}),
                        ('style',{'lists':{'image':{'backgroundImage':'url(https://example.test/background.png)'}}}),
                        ('style',{'lists':{'content':{'html':'<p>Keep</p>'}}})]
        for key,value in changes_to_try:
            node=avatar();node[key]=value;ape=page(node);before=copy.deepcopy(ape)
            out,changes=self.normalize(ape)
            self.assertEqual(out,before);self.assertEqual(changes,[]);self.assertEqual(ape,before)

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

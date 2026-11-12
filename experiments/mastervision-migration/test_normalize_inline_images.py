"""Synthetic static image extraction; no I/O, network or private source content."""
import base64
import copy
import importlib.util
from pathlib import Path
import re
import unittest

from importer import Review
from normalize_inline_images import normalize_inline_images, Content, CODE

spec=importlib.util.spec_from_file_location('inline_test_html',Path(__file__).resolve().parents[2]/'lms/lms/avo_html_fragment.py')
static=importlib.util.module_from_spec(spec);spec.loader.exec_module(static)
URL='https://f1.autoweboffice.ru/synthetic.png?key=a&other=b'
TAG='<img alt="" src="https://f1.autoweboffice.ru/synthetic.png?key=a&amp;other=b">'


def page(markup,kind='text',**fields):
    return {'name':'page','children':[{'id':'original-text','name':kind,'fields':{'html':markup,**fields},'children':[]}]}


def content(markup):
    parser=Content();parser.feed(markup);parser.close()
    return ''.join(parser.text),parser.links,parser.images


class InlineImageTests(unittest.TestCase):
    def normalize(self,ape):return normalize_inline_images(ape,static.make_html_block)

    def assert_conserved(self,markup,nodes):
        original=content(markup);text=[];links=[];images=[]
        for node in nodes:
            if node['name']=='image':images.append(node['fields']['imageSrc'])
            else:
                fragment=node['fields']['html'];static.make_html_block(fragment)
                values=content(fragment);text.append(values[0]);links.extend(values[1])
        self.assertEqual((''.join(text),links,images),original)

    def test_image_then_text_with_links_matches_observed_plain_paragraph(self):
        markup='<p>'+TAG+'Keep {name}<br><a href="https://example.test/one">One</a><br><a href="https://example.test/two" target="_blank">Two</a></p>'
        original=page(markup);before=copy.deepcopy(original);out,changes=self.normalize(original)
        self.assertEqual([x['name'] for x in out['children']],['image','text'])
        self.assertEqual(out['children'][0]['fields']['imageSrc'],URL)
        self.assertEqual(out['children'][1]['id'],'original-text')
        self.assert_conserved(markup,out['children']);self.assertEqual(original,before)
        self.assertEqual(changes,[{'path':[0],'code':CODE,'images':1,'sized_images':0}])

    def test_middle_image_splits_balanced_nested_text_without_losing_order(self):
        markup='<div><p><strong>Before &amp; first</strong>'+TAG+'<em>After &#160; second</em></p></div>'
        out,_=self.normalize(page(markup))
        self.assertEqual([x['name'] for x in out['children']],['text','image','text'])
        self.assert_conserved(markup,out['children'])
        self.assertEqual(out['children'][0]['fields']['html'],'<div><p><strong>Before &amp; first</strong></p></div>')
        self.assertEqual(out['children'][2]['fields']['html'],'<div><p><em>After &#160; second</em></p></div>')

    def test_two_images_consecutive_and_image_only_wrappers(self):
        markup='<p><b>'+TAG+TAG+'</b></p>'
        out,changes=self.normalize(page(markup))
        self.assertEqual([x['name'] for x in out['children']],['image','image'])
        self.assert_conserved(markup,out['children']);self.assertEqual(changes[0]['images'],2)
        self.assertEqual(len({x['id'] for x in out['children']}),2)

    def test_safe_sizing_accepted_and_recorded_without_inventing_content(self):
        tag='<img src="https://example.test/image.png" alt="" width="240" height="180" style="width: 240px; height: auto;">'
        markup='<p><b>'+tag+'</b></p><p style="text-align: center;">Keep</p><ul><li>Task</li></ul>'
        out,changes=self.normalize(page(markup,anchor=''))
        self.assert_conserved(markup,out['children']);self.assertEqual(changes[0]['sized_images'],1)
        self.assertEqual(out['children'][0]['fields'],{'anchor':'','imageSrc':'https://example.test/image.png'})

    def test_whitespace_entities_empty_links_and_other_static_content_preserved(self):
        markup='<p>\n<a href="https://example.test/empty"></a> &nbsp;'+TAG+' \n</p><hr>'
        out,_=self.normalize(page(markup));self.assert_conserved(markup,out['children'])

    def test_canonical_base64_image_uri_preserved_without_network(self):
        uri='data:image/png;base64,'+base64.b64encode(b'\x89PNG\r\n\x1a\n').decode()
        out,_=self.normalize(page('<p><img src="'+uri+'">Text</p>'))
        self.assertEqual(out['children'][0]['fields']['imageSrc'],uri)
        alias='data:image/jpg;base64,'+base64.b64encode(b'\xff\xd8\xff\xd9').decode()
        out,_=self.normalize(page('<img src="'+alias+'">'))
        self.assertEqual(out['children'][0]['fields']['imageSrc'],alias)
        for bad in ('data:image/svg+xml;base64,PHN2Zy8+','data:image/png;base64,YR==','javascript:alert(1)','data:text/html;base64,PHAvPg=='):
            with self.assertRaises(Review):self.normalize(page('<img src="'+bad+'">'))

    def test_deterministic_short_valid_ids_and_idempotence(self):
        original=page('<p>Before'+TAG+'After</p>')
        out,changes=self.normalize(original)
        self.assertEqual(self.normalize(original),(out,changes))
        for node in out['children']:
            self.assertLessEqual(len(node['id']),80);self.assertRegex(node['id'],r'^[A-Za-z0-9_-]+$')
        self.assertEqual(self.normalize(out),(out,[]))

    def test_generated_id_collision_with_existing_ape_node_is_reviewed(self):
        original=page('<p>'+TAG+'</p>');out,_=self.normalize(original)
        duplicate={'name':'text','id':out['children'][0]['id'],'fields':{'html':'Existing'},'children':[]}
        original['children'].append(duplicate)
        with self.assertRaisesRegex(Review,'inline_image_id_collision'):self.normalize(original)

    def test_code_html_becomes_static_text_parts_and_keeps_original_fields(self):
        markup='<p>Before'+TAG+'After</p>'
        out,_=self.normalize(page(markup,'code',anchor=''))
        self.assertEqual([x['name'] for x in out['children']],['text','image','text'])
        self.assertEqual(out['children'][0]['fields']['anchor'],'');self.assert_conserved(markup,out['children'])

    def test_image_inside_anchor_table_or_list_is_not_silently_detached(self):
        for markup in ('<a href="https://example.test/">'+TAG+'</a>','<table><tbody><tr><td>'+TAG+'</td></tr></tbody></table>',
                       '<ul><li>'+TAG+'</li></ul>','<ol>'+TAG+'</ol>','<p id="target">'+TAG+'</p>'):
            with self.assertRaisesRegex(Review,'context_requires_review'):self.normalize(page(markup))

    def test_nonempty_alt_unknown_attributes_and_srcset_are_reviewed(self):
        attributes=['alt="Visible caption"','onclick="bad()"','srcset="https://example.test/2x.png 2x"',
                    'data-main-class="image"','class="unknown"']
        for extra in attributes:
            with self.assertRaises(Review):self.normalize(page('<img src="https://example.test/image.png" '+extra+'>'))
        getcourse='<img src="https://example.test/image.png" data-main-class="image" data-hash="synthetic" data-image-editable="true" data-param="{}">'
        with self.assertRaisesRegex(Review,'attributes_require_review'):self.normalize(page(getcourse))

    def test_exact_getcourse_editor_metadata_is_recorded_without_changing_src_or_text(self):
        attrs=' data-main-class="lt-image-common" data-param="image" data-image-editable="true" data-hash="'+'a'*32+'.png"'
        tag='<img src="https://example.test/image.png"'+attrs+'>'
        markup='<p>Before</p><p>'+tag+'</p><p>After <a href="https://example.test/file">File</a></p>'
        out,changes=self.normalize(page(markup))
        self.assert_conserved(markup,out['children'])
        self.assertEqual(changes[0]['editor_metadata_images'],1)
        for wrong in (attrs.replace('lt-image-common','other-class'),attrs.replace('data-param="image"','data-param="crop"'),
                      attrs.replace('editable="true"','editable="false"'),attrs.replace('a'*32+'.png','wrong-hash'),
                      attrs.replace(' data-param="image"','')):
            with self.assertRaisesRegex(Review,'attributes_require_review'):
                self.normalize(page('<img src="https://example.test/image.png"'+wrong+'>'))

    def test_header_image_keeps_all_heading_html_and_drops_only_format_in_new_text(self):
        markup='<h4><b>Before '+TAG+' after</b></h4>'
        original=page(markup,'header',format='h4',anchor='');before=copy.deepcopy(original)
        out,changes=self.normalize(original)
        self.assertEqual([node['name']for node in out['children']],['text','image','text'])
        self.assert_conserved(markup,out['children'])
        self.assertEqual(out['children'][0]['fields'],{'html':'<h4><b>Before </b></h4>','anchor':''})
        self.assertEqual(out['children'][2]['fields'],{'html':'<h4><b> after</b></h4>','anchor':''})
        self.assertEqual(original,before);self.assertEqual(len(changes),1)
        for format in ('unknown','',None):
            with self.assertRaisesRegex(Review,'node_requires_review'):self.normalize(page(markup,'header',format=format))
        bad=page(markup,'header',format='h4');bad['children'][0]['future_setting']='keep'
        with self.assertRaisesRegex(Review,'node_requires_review'):self.normalize(bad)
        with self.assertRaisesRegex(Review,'node_requires_review'):self.normalize(page(TAG,'header',format='h4'))
        good=page('<h4><b>Already imported</b></h4>','header',format='h4')
        self.assertEqual(self.normalize(good),(good,[]))

    def test_unsafe_or_unknown_sizing_never_silently_dropped(self):
        for extra in ('width="0"','height="-1"','width="5000"','style="float:left"','style="width:0px"',
                      'style="width:url(x)"','style="width:1px;width:2px"'):
            with self.assertRaisesRegex(Review,'dimensions_require_review'):
                self.normalize(page('<img src="https://example.test/image.png" '+extra+'>'))

    def test_malformed_and_unsafe_remaining_markup_is_reviewed(self):
        cases=['<p>'+TAG,'<p><b>'+TAG+'</p></b>','<div/>'+TAG,TAG+'</img>',
               '<!-- comment -->'+TAG,'<!doctype html>'+TAG,
               '<p onclick="bad()">'+TAG+'Keep</p>','<script>bad()</script>'+TAG,
               '<a href="javascript:bad()">Keep</a>'+TAG,
               '<img src="https://example.test/a.png" src="https://example.test/b.png">']
        for markup in cases:
            original=page(markup);before=copy.deepcopy(original)
            with self.assertRaises(Review):self.normalize(original)
            self.assertEqual(original,before)

    def test_image_only_unsafe_wrappers_never_disappear_without_validation(self):
        for markup in ('<form>'+TAG+'</form>','<p onclick="bad()">'+TAG+'</p>',
                       '<div unknown="setting">'+TAG+'</div>','<custom-widget>'+TAG+'</custom-widget>',
                       '<iframe src="https://drive.google.com/file/d/synthetic/preview" width="640" height="480">'+TAG+'</iframe>'):
            ape=page(markup);before=copy.deepcopy(ape)
            with self.assertRaises(Review):self.normalize(ape)
            self.assertEqual(ape,before)

    def test_candidate_node_settings_and_children_require_review(self):
        for field,value in [('anchor','keep'),('unknown','')]:
            with self.assertRaisesRegex(Review,'node_requires_review'):self.normalize(page(TAG,**{field:value}))
        ape=page(TAG);ape['children'][0]['children']=[{'name':'text','fields':{'html':'Child'}}]
        with self.assertRaisesRegex(Review,'node_requires_review'):self.normalize(ape)

    def test_unknown_nodes_and_existing_good_nodes_have_identical_fingerprint(self):
        original={'name':'page','children':[{'name':'future','fields':{'html':TAG}},
                  {'name':'text','id':'keep','fields':{'html':'<p>Existing</p>'}}]}
        self.assertEqual(self.normalize(original),(original,[]))

    def test_original_paths_stable_when_multiple_nodes_expand(self):
        ape={'name':'page','children':[page(TAG)['children'][0],{'name':'section','children':[page(TAG)['children'][0]]}]}
        # Original IDs are not introduced again on image-only replacements.
        out,changes=self.normalize(ape)
        self.assertEqual([x['path'] for x in changes],[[0],[1,0]])
        self.assertNotEqual(out['children'][0]['id'],out['children'][1]['children'][0]['id'])


if __name__=='__main__':unittest.main()

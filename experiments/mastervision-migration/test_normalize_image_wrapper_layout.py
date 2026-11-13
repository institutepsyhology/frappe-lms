import copy
import unittest
from unittest.mock import patch

from importer import Review
import normalize_image_wrapper_layout as mod
from normalize_inline_images import normalize_inline_images, Content
from normalize_source import static_validator

IMG='<img src="https://example.test/image.png" width="280" height="280">'
def page(markup): return {'name':'page','children':[{'id':'text','name':'text','fields':{'html':markup},'style':{}}]}
def material(markup):
    p=Content();p.feed(markup);p.close();return p.text,p.links,p.images


class ImageWrapperTests(unittest.TestCase):
    def clean(self, markup): return mod.normalize_image_wrapper_layout(page(markup), static_validator())

    def test_nested_image_only_spans_preserve_exact_material_and_prepare_for_extraction(self):
        source='<p>First</p><span style="display:inline-block; height:281px; width:280px"><span style="height:280px">'+IMG+'</span></span><p><a href="https://example.test/notes">Notes</a> Last</p>'
        original=page(source);saved=copy.deepcopy(original)
        out,changes=mod.normalize_image_wrapper_layout(original,static_validator())
        self.assertEqual(original,saved);self.assertEqual(changes,[{'path':[0],'code':mod.CODE,'wrappers':2,'images':1}])
        cleaned=out['children'][0]['fields']['html'];self.assertEqual(material(source),material(cleaned))
        self.assertIn(IMG,cleaned)
        extracted,_=normalize_inline_images(out,static_validator())
        self.assertEqual(sum(n['name']=='image' for n in extracted['children']),1)
        self.assertEqual(mod.normalize_image_wrapper_layout(out,static_validator()),(out,[]))

    def test_multiple_image_wrappers_keep_image_order_and_links(self):
        second=IMG.replace('image.png','second.png')
        source='<p><a href="https://example.test/file">File</a></p>'+''.join('<span style="display:inline-block;height:380px">'+i+'</span>' for i in (IMG,second))
        out,changes=self.clean(source)
        self.assertEqual(changes[0]['images'],2)
        self.assertEqual(material(source),material(out['children'][0]['fields']['html']))

    def test_text_links_hidden_styles_and_non_image_only_spans_stay_untouched(self):
        for inner in ('Visible '+IMG,'<a href="https://example.test/file">'+IMG+'</a>',IMG+IMG):
            source='<span style="display:inline-block;height:280px">'+inner+'</span>'
            self.assertEqual(self.clean(source),(page(source),[]))
        for css in ('display:none;height:280px','display:inline-block;height:0px',
                    'display:inline-block;height:280px;opacity:0',
                    'display:inline-block;height:280px;background-image:url(x)',
                    'display:inline-block;height:280px;content:meaningful',
                    'display:inline-block;height:280px;display:block'):
            source='<span style="'+css+'">'+IMG+'</span>'
            self.assertEqual(self.clean(source),(page(source),[]))

    def test_unknown_attributes_conditions_and_media_remain_protected(self):
        for extra in (' onclick="go()"',' id="anchor"',' data-action="show"'):
            source='<span style="display:inline-block;height:280px"'+extra+'>'+IMG+'</span>'
            self.assertEqual(self.clean(source),(page(source),[]))
        source='<span style="display:inline-block;height:280px">'+IMG+'</span>'
        tree=page(source);tree['children'][0]['fields']['visibleConditions']={'paid':True}
        self.assertEqual(mod.normalize_image_wrapper_layout(tree,static_validator()),(tree,[]))

    def test_accepted_source_keeps_exact_fingerprint(self):
        source='<span style="width:280px">'+IMG+'</span>'
        self.assertEqual(self.clean(source),(page(source),[]))

    def test_typed_visual_font_controls_are_retained_without_becoming_captions(self):
        source='<span style="display:inline-block;height:280px">'+IMG+'</span>'
        tree=page(source);tree['children'][0]['style']={'lists':{'text':{'color':{'value':None},'fontSize':{'value':'16px'}}}}
        out,changes=mod.normalize_image_wrapper_layout(tree,static_validator())
        self.assertTrue(changes);self.assertEqual(out['children'][0]['style'],tree['children'][0]['style'])
        tree['children'][0]['style']['lists']['text']['caption']='Keep educational caption'
        self.assertEqual(mod.normalize_image_wrapper_layout(tree,static_validator()),(tree,[]))

    def test_material_mismatch_is_fatal(self):
        source='<span style="display:inline-block;height:280px">'+IMG+'</span>'
        with patch.object(mod,'_material',side_effect=[['before'],['after']]):
            with self.assertRaisesRegex(Review,'image_wrapper_material_mismatch'):self.clean(source)


if __name__=='__main__':unittest.main()

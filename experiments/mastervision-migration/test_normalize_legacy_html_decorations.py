"""Synthetic source-fidelity regressions; no production lesson content or network."""
import copy
import hashlib
import unittest
from unittest.mock import patch

from importer import Review
from normalize_editor_nodes import _core
from normalize_source import static_validator
from normalize_static_presentation import _material
import normalize_legacy_html_decorations as mod


MATERIAL = '<p>Read &amp; practise&nbsp;now. <a href="https://example.test/a?x=1&amp;y=2">Notes</a></p>'
BUTTON = '<div class="talks-widget-button"></div>'


def page(html, **fields):
    return {'name':'page','children':[{'name':'text','id':'synthetic',
        'fields':{'html':html,'anchor':'',**fields},'style':{'spacing':{'margin':'12px'}}}]}


def payload(ape):
    return {'account':'mastervision','source_origin':'https://shop.mastervision.su',
            'course_id':7,'lesson_id':11,'course_title':'Synthetic course','lesson_title':'Synthetic lesson',
            'format':'ape','ape':ape}


class DecorationsTests(unittest.TestCase):
    def normalize(self, ape):return mod.normalize_legacy_html_decorations(ape,static_validator())

    def test_single_empty_widget_is_sliced_and_all_material_bytes_preserved(self):
        source='<div>'+MATERIAL+'\n'+BUTTON+'<p>After.</p></div>'
        ape=page(source);before=copy.deepcopy(ape);out,changes=self.normalize(ape)
        expected=source.replace(BUTTON,'')
        self.assertEqual(out['children'][0]['fields']['html'],expected)
        self.assertEqual(ape,before);self.assertEqual(out['children'][0]['style'],ape['children'][0]['style'])
        self.assertEqual(changes,[{'path':[0],'code':mod.CODE,'empty_widgets':1,'inline_displays':0}])
        self.assertEqual(self.normalize(out),(out,[]))

    def test_only_verified_layout_whitespace_in_widget_can_be_omitted(self):
        for empty in (' \n\t','&nbsp;','&#160;'):
            source=MATERIAL+BUTTON.replace('></div>','>'+empty+'</div>')
            out,_=self.normalize(page(source));self.assertEqual(out['children'][0]['fields']['html'],MATERIAL)
        for content in ('Authored answer','\u200b','<span></span>',
                        '<a href="https://example.test/answer">Answer</a>','<!-- comment -->',
                        '<img src="https://example.test/a.png">','<script>private()</script>'):
            ape=page(MATERIAL+BUTTON.replace('></div>','>'+content+'</div>'));before=copy.deepcopy(ape)
            with self.subTest(content=content),self.assertRaises(Review):self.normalize(ape)
            self.assertEqual(ape,before)

    def test_style_hash_is_required_for_nonempty_widget_css(self):
        synthetic='position:fixed;right:1px;'
        source=MATERIAL+BUTTON.replace('class=','style="'+synthetic+'" class=')
        with self.assertRaises(Review):self.normalize(page(source))
        with patch.object(mod,'KNOWN_BUTTON_STYLES',{hashlib.sha256(synthetic.encode()).hexdigest()}):
            out,_=self.normalize(page(source))
        self.assertEqual(out['children'][0]['fields']['html'],MATERIAL)

    def test_unknown_attributes_classes_widget_ids_and_duplicate_widgets_are_protected(self):
        for button in (BUTTON.replace('class=','id="preserve-anchor" class='),
                       BUTTON.replace('class=','onclick="private()" class='),
                       BUTTON.replace('class=','data-unknown="" class='),
                       BUTTON.replace('talks-widget-button','talks-widget-button other'),BUTTON+BUTTON):
            with self.subTest(button=button),self.assertRaises(Review):self.normalize(page(MATERIAL+button))

    def test_inline_important_on_inline_elements_preserves_text_links_and_other_styles(self):
        for tag in ('a','span','br'):
            href=' href="https://example.test/read?x=1&amp;y=2"'if tag=='a'else''
            opening='<'+tag+href+' style="color:red; display: inline !important; background-color:white;">'
            markup=MATERIAL+opening+(''if tag=='br'else'Read &amp; keep</'+tag+'>')
            ape=page(markup);before=copy.deepcopy(ape);out,changes=self.normalize(ape)
            cleaned=out['children'][0]['fields']['html']
            self.assertNotIn('display:',cleaned);self.assertIn('color:red;',cleaned)
            self.assertIn('background-color:white;',cleaned)
            self.assertEqual(_material(markup),_material(cleaned));self.assertEqual(ape,before)
            self.assertEqual(changes[0]['inline_displays'],1)

    def test_only_display_style_can_be_removed_with_no_empty_attribute(self):
        for quote in ('"',"'"):
            markup=MATERIAL+'<br style='+quote+'display:inline!important'+quote+'>'
            out,_=self.normalize(page(markup));self.assertEqual(out['children'][0]['fields']['html'],MATERIAL+'<br>')

    def test_hidden_or_nondefault_display_never_becomes_visible(self):
        for style in ('display:none','display:none!important','display:block!important',
                      'display:inline-block!important','display:contents','display:inline!important;display:none'):
            # A real candidate elsewhere cannot authorize unknown or hidden CSS.
            markup=MATERIAL+'<br style="display:inline!important"><span style="'+style+'">Preserve.</span>'
            ape=page(markup);before=copy.deepcopy(ape)
            with self.subTest(style=style),self.assertRaises(Review):self.normalize(ape)
            self.assertEqual(ape,before)
        markup=MATERIAL+'<span style="display:none">Preserve.</span>'
        self.assertEqual(self.normalize(page(markup)),(page(markup),[]))

    def test_block_element_display_or_unquoted_styles_require_review(self):
        for markup in (MATERIAL+'<div style="display:inline!important">Keep.</div>',
                       MATERIAL+'<br style=display:inline!important>'):
            with self.assertRaises(Review):self.normalize(page(markup))

    def test_full_html_is_validated_including_empty_unsafe_ancestors(self):
        for markup in ('<form>'+MATERIAL+BUTTON+'</form>',
                       '<div onclick="private()">'+MATERIAL+BUTTON+'</div>',
                       MATERIAL+BUTTON+'<script>private()</script>',
                       MATERIAL+BUTTON+'<p><b>Malformed</p></b>',
                       MATERIAL+BUTTON+'<!-- Unknown comment -->',
                       MATERIAL+'<div class="talks-widget-button"/>'):
            with self.subTest(markup=markup),self.assertRaises(Review):self.normalize(page(markup))

    def test_protected_nodes_conditions_children_and_caption_styles_are_unchanged(self):
        for fields in ({'anchor':'keep'},{'visibleConditions':{'active':True}},{'displayDelay':3},{'unknown':None}):
            ape=page(MATERIAL+BUTTON,**fields);self.assertEqual(self.normalize(ape),(ape,[]))
        for key,value in (('children',[{'name':'text','fields':{'html':'Child'}}]),
                          ('style',{'caption':'Keep'}),('unknown',None)):
            ape=page(MATERIAL+BUTTON);ape['children'][0][key]=value
            self.assertEqual(self.normalize(ape),(ape,[]))
        ape={'name':'page','fields':{'visibleConditions':{'active':True}},'children':page(MATERIAL+BUTTON)['children']}
        self.assertEqual(self.normalize(ape),(ape,[]))

    def test_typed_visual_font_controls_are_preserved_but_urls_and_unknown_styles_are_protected(self):
        style={'lists':{'text':{'color':{'value':'#000000'},'fontSize':{'value':'18px'},
                               'marginTop':{'number':2,'units':'px'}},'content':{'justifyContent':{'value':'center'}}}}
        ape=page(MATERIAL+BUTTON);ape['children'][0]['style']=style;before=copy.deepcopy(ape)
        out,changes=self.normalize(ape)
        self.assertEqual(out['children'][0]['style'],style);self.assertEqual(ape,before);self.assertEqual(len(changes),1)
        for bad in ({'caption':{'value':'Preserve'}},{'color':{'value':'url(https://example.test/a)'}},
                    {'fontSize':{'unknown':'18px'}},{'html':{'value':'<p>Preserve</p>'}}):
            ape=page(MATERIAL+BUTTON);ape['children'][0]['style']={'lists':{'text':bad}}
            self.assertEqual(self.normalize(ape),(ape,[]))

    def test_noop_accepted_bytes_and_future_validator_remain_exact(self):
        for html in (MATERIAL,' <p>Already accepted.</p> ','<div class="unknown">Keep.</div>'):
            ape=page(html);self.assertEqual(self.normalize(ape),(ape,[]))
        ape=page(MATERIAL+BUTTON)
        self.assertEqual(mod.normalize_legacy_html_decorations(ape,lambda _:True),(ape,[]))

    def test_real_core_accepts_both_repairs_and_keeps_authored_material(self):
        for markup in (MATERIAL+BUTTON,MATERIAL+'<br style="display:inline !important">'):
            original=payload(page(markup));self.assertIn('unsafe_or_unrecognized_html',_core().plan_import(original)['issues'])
            ape,_=self.normalize(original['ape']);converted=copy.deepcopy(original);converted['ape']=ape
            after=_core().plan_import(converted);self.assertTrue(after['ready']);self.assertEqual(after['issues'],[])
            expected=markup.replace(BUTTON,'').replace(' style="display:inline !important"','')
            self.assertEqual(after['blocks'],_core().plan_import(payload(page(expected)))['blocks'])

    def test_invalid_api_and_empty_widget_only_never_claim_a_real_lesson(self):
        for ape in ({},[],{'name':'page','children':[None]}):
            with self.assertRaises(Review):self.normalize(ape)
        with self.assertRaises(Review):mod.normalize_legacy_html_decorations(page(MATERIAL+BUTTON),None)
        with self.assertRaises(Review):self.normalize(page(BUTTON))


if __name__=='__main__':unittest.main()

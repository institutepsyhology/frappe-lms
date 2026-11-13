"""Synthetic keyboard-markup regressions; no lesson content or network."""
import copy
import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch

from importer import Review
import normalize_keyboard_markup as module
from normalize_static_presentation import _material

spec = importlib.util.spec_from_file_location('keyboard_markup_test_validator',
    Path(__file__).resolve().parents[2] / 'lms/lms/avo_html_fragment.py')
static = importlib.util.module_from_spec(spec); spec.loader.exec_module(static)
VALIDATE = static.make_html_block
STYLE = ('box-sizing: border-box; font-family: Menlo, Monaco, Consolas, "Courier New", monospace; '
         'font-size: 12.6px; padding: 0.2rem 0.4rem; color: rgba(255, 255, 255, 0.85); '
         'background: rgb(0, 0, 0); border-radius: 4px; '
         'box-shadow: rgba(0, 0, 0, 0.25) 0px -1px 0px inset; display: inline-block; '
         'line-height: 1; white-space: nowrap;')


def page(markup, **fields):
    return {'name':'page','children':[{'id':'synthetic','name':'text',
        'fields':{'html':markup,'anchor':'',**fields},'children':[]}]}


class KeyboardTests(unittest.TestCase):
    def normalize(self, ape): return module.normalize_keyboard_markup(ape, VALIDATE)

    def test_observed_presentation_keeps_text_entities_children_links_and_font(self):
        markup = '<p>Before\n <kbd style=\'' + STYLE + '\'><strong>Ctrl&nbsp;+</strong> A &amp; B</kbd> after <a href="https://example.test/material?a=1&amp;b=2">File</a></p>'
        ape=page(markup);before=copy.deepcopy(ape);out,changes=self.normalize(ape)
        cleaned=out['children'][0]['fields']['html'];VALIDATE(cleaned)
        self.assertEqual(_material(markup),_material(cleaned))
        self.assertIn('font-family: Menlo, Monaco, Consolas, &quot;Courier New&quot;, monospace',cleaned)
        self.assertNotIn('<kbd',cleaned);self.assertNotIn('border-radius',cleaned)
        self.assertNotIn('box-shadow',cleaned);self.assertNotIn('display:',cleaned)
        self.assertEqual(changes,[{'path':[0],'code':module.CODE,'keyboard_elements':1,
                                  'presentation_removed':3}])
        self.assertEqual(ape,before)

    def test_attribute_free_keyboard_gets_default_monospace_and_is_idempotent(self):
        out,changes=self.normalize(page('<p><kbd>\tEsc\n Enter</kbd></p>'))
        self.assertIn('<span style="font-family:monospace">\tEsc\n Enter</span>',out['children'][0]['fields']['html'])
        self.assertEqual(changes[0]['presentation_removed'],0)
        again,new=self.normalize(out);self.assertEqual(again,out);self.assertEqual(new,[])

    def test_multiple_elements_tables_lists_links_and_iframe_src_stay_in_order(self):
        markup=('<ol start="2"><li><kbd>One</kbd><a href="https://one.test/">A</a></li>'
                '<li><kbd>Two</kbd></li></ol><table><tbody><tr><td>Left</td><td>Right</td>'
                '</tr></tbody></table><iframe src="https://drive.google.com/file/d/synthetic/preview" width="640" height="480"></iframe>')
        out,changes=self.normalize(page(markup));cleaned=out['children'][0]['fields']['html']
        self.assertEqual(_material(markup),_material(cleaned));VALIDATE(cleaned)
        self.assertEqual(changes[0]['keyboard_elements'],2)

    def test_accepted_bytes_and_markup_without_keyboard_remain_exact(self):
        for markup in (' \n<p>Accepted&nbsp; text</p> ', '<div class="unknown">Keep</div>'):
            ape=page(markup);out,changes=self.normalize(ape)
            self.assertEqual(out,ape);self.assertEqual(changes,[])
        ape=page('<kbd>Accepted by future validator</kbd>')
        out,changes=module.normalize_keyboard_markup(ape,lambda _: True)
        self.assertEqual(out,ape);self.assertEqual(changes,[])

    def test_only_exact_observed_decorative_values_on_keyboard_can_be_removed(self):
        bad=['border-radius:5px','box-shadow:rgba(0, 0, 0, 0.5) 0px -1px 0px inset',
             'display:none','display:inline-block!important','display:contents',
             'display:inline-block;display:none','color:red;display:inline-block; color:blue',
             'background:url(https://example.test/asset)', 'content:"hidden"',
             'counter-increment:item', 'width:expression(private())']
        for css in bad:
            with self.subTest(css=css),self.assertRaisesRegex(Review,'keyboard_markup_requires_review'):
                self.normalize(page('<kbd style=\''+css+'\'>Keep</kbd>'))
        with self.assertRaises(Review):
            self.normalize(page('<p style="display:inline-block"><kbd>Keep</kbd></p>'))

    def test_unknown_attributes_events_forms_scripts_styles_and_malformed_markup_review(self):
        for markup in ('<kbd onclick="private()">Keep</kbd>', '<kbd title="unknown">Keep</kbd>',
                       '<kbd class="unknown">Keep</kbd>', '<form><kbd>Keep</kbd></form>',
                       '<kbd>Keep<script>private()</script></kbd>', '<style>kbd{display:none}</style><kbd>Keep</kbd>',
                       '<kbd>Keep<!-- comment --></kbd>', '<kbd><strong>Keep</kbd></strong>',
                       '<kbd style="color:red" style="display:none">Keep</kbd>',
                       '<kbd/><p>Keep</p>'):
            ape=page(markup);before=copy.deepcopy(ape)
            with self.subTest(markup=markup),self.assertRaises(Review):self.normalize(ape)
            self.assertEqual(ape,before)

    def test_protected_fields_nodes_style_children_and_ancestors_remain_unchanged(self):
        for key,value in [('anchor','meaningful'),('visibleConditions',{'active':True}),
                          ('displayDelay',4),('unknown',None)]:
            ape=page('<kbd>Keep</kbd>',**{key:value});out,changes=self.normalize(ape)
            self.assertEqual(out,ape);self.assertEqual(changes,[])
        for key,value in [('style',{'caption':'Keep'}),('unknown',None),
                          ('children',[{'name':'text','fields':{'html':'Child'}}])]:
            ape=page('<kbd>Keep</kbd>');ape['children'][0][key]=value
            out,changes=self.normalize(ape);self.assertEqual(out,ape);self.assertEqual(changes,[])
        for fields in ({'visibleConditions':['protected']},{'anchor':'important'}):
            ape=page('<kbd>Keep</kbd>');ape['fields']=fields
            out,changes=self.normalize(ape);self.assertEqual(out,ape);self.assertEqual(changes,[])

    def test_known_visual_style_is_preserved_and_original_paths_stable(self):
        node=page('<kbd>Keep</kbd>')['children'][0]
        node['style']={'lists':{'text':{'width':{'value':{'number':100,'type':'number','units':'%'}},
                                      'fontSize':{'value':{'number':14,'units':'px'}},
                                      'color':{'value':{'r':0,'g':0,'b':0,'a':1,'enabled':True}}},
                               'content':{'justifyContent':{'value':{'type':'center'}}}}}
        ape={'name':'page','children':[{'name':'column','children':[node]}]};before=copy.deepcopy(ape)
        out,changes=self.normalize(ape);self.assertEqual(ape,before)
        self.assertEqual(changes[0]['path'],[0,0]);self.assertEqual(out['children'][0]['children'][0]['style'],node['style'])

    def test_unknown_or_material_content_style_is_not_a_visual_alignment_wrapper(self):
        for content in ({'justifyContent':{'value':{'type':'other'}}},
                        {'justifyContent':{'value':{'type':'center'}},'caption':'Keep'},
                        {'justifyContent':{'value':{'type':'center','url':'https://example.test/file'}}}):
            ape=page('<kbd>Keep</kbd>');ape['children'][0]['style']={'lists':{'content':content}}
            out,changes=self.normalize(ape);self.assertEqual(out,ape);self.assertEqual(changes,[])
        for key,value in [('fontSize',{'value':{'url':'https://example.test/file'}}),
                          ('caption','Keep'),('color','expression(private())')]:
            ape=page('<kbd>Keep</kbd>');ape['children'][0]['style']={'lists':{'text':{key:value}}}
            out,changes=self.normalize(ape);self.assertEqual(out,ape);self.assertEqual(changes,[])

    def test_material_loss_or_link_change_is_rejected(self):
        original=module._Keyboard.finish
        for old,new in [('Material','Lost'),('https://one.test/','https://other.test/')]:
            def broken(parser): return original(parser).replace(old,new)
            with patch.object(module._Keyboard,'finish',broken):
                with self.assertRaisesRegex(Review,'keyboard_markup_material_mismatch'):
                    self.normalize(page('<kbd>Material</kbd><a href="https://one.test/">A</a>'))

    def test_invalid_tree_or_validator_fails_with_fixed_code(self):
        for ape in ([],{'name':'page'},{'name':'text','children':[]},{'name':'page','children':[None]}):
            with self.assertRaisesRegex(Review,'keyboard_markup_source_invalid'):self.normalize(ape)
        with self.assertRaises(Review):module.normalize_keyboard_markup(page('Keep'),None)


if __name__=='__main__': unittest.main()

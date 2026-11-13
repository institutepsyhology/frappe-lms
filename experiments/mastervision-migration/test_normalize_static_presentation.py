"""Static synthetic presentation regressions; no real lesson text or network."""
import copy
import importlib.util
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from importer import Review
import normalize_static_presentation as module

spec = importlib.util.spec_from_file_location('static_presentation_test_validator',
    Path(__file__).resolve().parents[2] / 'lms/lms/avo_html_fragment.py')
static = importlib.util.module_from_spec(spec); spec.loader.exec_module(static)
VALIDATE = static.make_html_block


def page(markup, name='text', **fields):
    return {'name':'page','children':[{'id':'synthetic','name':name,'fields':{'html':markup,'anchor':'',**fields},'children':[]}]}


class PresentationTests(unittest.TestCase):
    def normalize(self, ape): return module.normalize_static_presentation(ape, VALIDATE)

    def test_inert_button_and_pre_keep_exact_text_entities_newlines_and_links(self):
        markup='<h1>Heading</h1><button><span>First &amp; second</span></button><pre>\tA\n  B&nbsp;C\n<a href="https://example.test/material">Text</a></pre>'
        ape=page(markup);before=copy.deepcopy(ape);out,changes=self.normalize(ape)
        html=out['children'][0]['fields']['html']
        self.assertIn('<span><span>First &amp; second</span></span>',html)
        self.assertIn('<div style="white-space:pre">\tA\n  B&nbsp;C\n',html)
        self.assertEqual(module._material(markup),module._material(html));VALIDATE(html)
        self.assertEqual(changes,[{'path':[0],'code':module.CODE,'presentation':{'buttons':1,'pre':1}}])
        self.assertEqual(ape,before)

    def test_word_alignment_hr_tab_stops_and_clipboard_preserve_material(self):
        markup=('<div align="center" style="font-family:Arial"><p data-pm-slice="1 1 []" '
                'style="tab-stops:list 36.0pt;font-size:14px">Before '
                '<a href="https://example.test/file?a=1&amp;b=2">Material</a> after.</p>'
                '<hr size="2" width="100%" align="center"></div>')
        out,changes=self.normalize(page(markup));html=out['children'][0]['fields']['html']
        self.assertIn('font-family:Arial;text-align:center',html)
        self.assertNotIn('tab-stops',html);self.assertNotIn('data-pm-slice',html)
        self.assertIn('<hr>',html);self.assertEqual(module._material(markup),module._material(html))
        self.assertEqual(changes[0]['presentation'],{'alignment':1,'hr_attributes':3,'clipboard':1,'tab_stops':1})
        VALIDATE(html)

    def test_existing_exact_alignment_is_not_duplicated_and_conflict_fails(self):
        markup='<div align="center" style="text-align:center"><p>Keep</p></div>'
        out,_=self.normalize(page(markup));self.assertEqual(out['children'][0]['fields']['html'].count('text-align:center'),1)
        with self.assertRaisesRegex(Review,'static_presentation_requires_review'):
            self.normalize(page(markup.replace('text-align:center','text-align:left')))

    def test_hr_without_align_and_clipboard_on_link_are_only_presentation(self):
        markup='<p><a href="https://one.test/file" data-pm-slice="2 2 []" style="tab-stops:list 36pt">One</a></p><hr width="80%" size="1">'
        out,_=self.normalize(page(markup));cleaned=out['children'][0]['fields']['html']
        self.assertEqual(module._material(markup),module._material(cleaned));VALIDATE(cleaned)

    def test_accepted_html_and_unknown_without_approved_change_stay_byte_exact(self):
        markup='\n <p style="text-align:center">A&nbsp; B <a href="https://one.test/">one</a></p>\n<hr> '
        for source in (markup,'<div class="unapproved">Keep unknown</div>'):
            ape=page(source);before=json.dumps(ape,ensure_ascii=False)
            out,changes=self.normalize(ape)
            self.assertEqual(json.dumps(out,ensure_ascii=False),before);self.assertEqual(changes,[])

    def test_unknown_scripts_forms_events_css_classes_comments_and_active_controls_review(self):
        values=['<pre>Keep<script>private()</script></pre>', '<form><button>Keep</button></form>',
                '<button onclick="private()">Keep</button>', '<pre class="unknown">Keep</pre>',
                '<button type="button">Keep</button>', '<div align="center" class="unapproved">Keep</div>',
                '<div align="center" style="background-image:url(https://example.test/i.png)">Keep</div>',
                '<div align="center" style="position:absolute">Keep</div>',
                '<pre>Keep<!-- unknown --></pre>', '<pre>Keep<input value="material"></pre>']
        for source in values:
            ape=page(source);before=copy.deepcopy(ape)
            with self.subTest(source=source),self.assertRaisesRegex(Review,'static_presentation_requires_review'):
                self.normalize(ape)
            self.assertEqual(ape,before)

    def test_malformed_or_unapproved_presentation_values_are_never_guessed(self):
        values=['<div align="absolute">Keep</div>','<div align="center" align="right">Keep</div>',
                '<p data-pm-slice="1 1 [\"unknown\"]">Keep</p>', '<p data-pm-slice="999 1 []">Keep</p>',
                '<p style="tab-stops:expression(private())">Keep</p>', '<p style="tab-stops:unknown">Keep</p>',
                '<hr width="200%">','<hr size="0">','<pre>Keep</div>']
        for source in values:
            with self.subTest(source=source),self.assertRaises(Review):self.normalize(page(source))

    def test_table_cells_lists_and_ordered_links_never_reorder(self):
        markup=('<div align="left"><ol start="3"><li><a href="https://one.test/">First</a></li>'
                '<li>Second</li></ol><table><tbody><tr><td><pre> X\n Y </pre></td>'
                '<td><a href="https://two.test/">Other</a></td></tr></tbody></table></div>')
        out,_=self.normalize(page(markup));cleaned=out['children'][0]['fields']['html']
        self.assertEqual(module._material(markup),module._material(cleaned));VALIDATE(cleaned)

    def test_approved_iframe_src_is_preserved_but_images_wait_for_separate_pass(self):
        markup='<div align="center"><iframe src="https://drive.google.com/file/d/syntheticID/preview" width="640" height="480"></iframe></div>'
        out,_=self.normalize(page(markup));self.assertEqual(module._material(markup),module._material(out['children'][0]['fields']['html']))
        ape=page('<div align="center"><img src="https://example.test/image.png"></div>');before=copy.deepcopy(ape)
        with self.assertRaises(Review):self.normalize(ape)
        self.assertEqual(ape,before)

    def test_protected_fields_styles_actions_and_unknown_metadata_remain_untouched(self):
        for key,value in [('anchor','important'),('visibleConditions',{'condition':'protected'}),
                          ('displayDelay',3),('unknown',None)]:
            ape=page('<pre>Keep</pre>',**{key:value});out,changes=self.normalize(ape)
            self.assertEqual(out,ape);self.assertEqual(changes,[])
        for key,value in [('style',{'caption':'Keep'}),('extra',None),
                          ('children',[{'name':'text','fields':{'html':'Child'}}])]:
            ape=page('<pre>Keep</pre>');ape['children'][0][key]=value
            out,changes=self.normalize(ape);self.assertEqual(out,ape);self.assertEqual(changes,[])
        for key in ('event','toAnchor','icon'):
            ape=page('<pre>Keep</pre>','button',linkType='url',url='https://example.test/',**{key:'meaningful'})
            out,changes=self.normalize(ape);self.assertEqual(out,ape);self.assertEqual(changes,[])

    def test_protected_ancestor_is_not_bypassed_and_original_paths_are_stable(self):
        ape=page('<pre>Keep</pre>');ape['fields']={'visibleConditions':['protected']}
        out,changes=self.normalize(ape);self.assertEqual(out,ape);self.assertEqual(changes,[])
        ape={'name':'page','children':[{'name':'column','children':[page('<pre>One</pre>')['children'][0]]},page('<button>Two</button>')['children'][0]]}
        before=copy.deepcopy(ape);out,changes=self.normalize(ape)
        self.assertEqual([c['path'] for c in changes],[[0,0],[1]]);self.assertEqual(ape,before)
        second,again=self.normalize(out);self.assertEqual(second,out);self.assertEqual(again,[])

    def test_known_visual_text_style_is_preserved_but_media_and_unknown_style_remain_protected(self):
        style={'lists':{'text':{'width':'auto','height':'auto','backgroundImage':'none',
                               'marginTop':'0px','textAlign':'left'}}}
        ape=page('<pre>Keep\n spaces</pre>');ape['children'][0]['style']=copy.deepcopy(style)
        out,changes=self.normalize(ape)
        self.assertTrue(changes);self.assertEqual(out['children'][0]['style'],style)
        for extra,value in [('caption','Keep text'),('backgroundImage','url(https://example.test/background.png)'),
                            ('width','expression(private())'),('width',{'unknown':'value'})]:
            protected=copy.deepcopy(ape);protected['children'][0]['style']['lists']['text'][extra]=value
            out,changes=self.normalize(protected);self.assertEqual(out,protected);self.assertEqual(changes,[])

    def test_observed_editor_value_controls_are_visual_not_lesson_text(self):
        style={'lists':{'text':{
            'width':{'value':{'number':100,'type':'number','units':'%'}},
            'backgroundImage':{'value':{'url':''}},
            'backgroundColor':{'value':{'enabled':False,'r':0,'g':0,'b':0,'a':1}},
            'height':{'value':{'type':'auto'}},
        }}}
        ape=page('<div align="center"><p>Keep</p></div>');ape['children'][0]['style']=copy.deepcopy(style)
        out,changes=self.normalize(ape);self.assertTrue(changes)
        self.assertEqual(out['children'][0]['style'],style)
        for field,value in [('width',{'value':{'caption':'Keep'}}),
                            ('backgroundImage',{'value':{'url':'https://example.test/background.png'}})]:
            protected=copy.deepcopy(ape);protected['children'][0]['style']['lists']['text'][field]=value
            out,changes=self.normalize(protected);self.assertEqual(out,protected);self.assertEqual(changes,[])

    def test_material_loss_or_changed_link_is_rejected_even_if_result_is_safe_html(self):
        original=module._Cleaner.finish
        for before,after in [('Material','Lost'),('https://one.test/','https://other.test/')]:
            def broken(parser):return original(parser).replace(before,after)
            with patch.object(module._Cleaner,'finish',broken):
                with self.assertRaisesRegex(Review,'static_presentation_material_mismatch'):
                    self.normalize(page('<button>Material <a href="https://one.test/">one</a></button>'))

    def test_invalid_tree_or_validator_fails_with_fixed_code(self):
        for ape in ([],{'name':'page'},{'name':'text','children':[]}, {'name':'page','children':[None]}):
            with self.assertRaisesRegex(Review,'static_presentation_source_invalid'):self.normalize(ape)
        with self.assertRaises(Review):module.normalize_static_presentation(page('Text'),None)


if __name__=='__main__':
    unittest.main()

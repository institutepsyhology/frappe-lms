"""Formatted native-button regressions use synthetic educational source only."""
import copy
import base64
from html.parser import HTMLParser
import importlib.util
import json
from pathlib import Path
import unittest

from importer import Review
from normalize_button_labels import CODE, normalize_button_labels
from normalize_editor_nodes import _core

spec = importlib.util.spec_from_file_location('button_test_static', Path(__file__).resolve().parents[2] / 'lms/lms/avo_html_fragment.py')
static = importlib.util.module_from_spec(spec); spec.loader.exec_module(static)
VALIDATE = static.make_html_block
URL = 'https://example.test/material?first=1&second=2'


def button(label='<span style="font-size: 18px;">Audio</span>', **fields):
    return {'id':'native-button','name':'button','fields':{'anchor':'','html':label,'icon':'',
        'linkType':'url','url':URL,'blank':False,'toAnchor':'','event':'',**fields},
        'style':{'spacing':{'margin':'12px'}},'children':[]}


def page(*nodes): return {'name':'page','children':list(nodes)}


class Contents(HTMLParser):
    def __init__(self): super().__init__(convert_charrefs=True); self.text=[]; self.links=[]
    def handle_data(self, data): self.text.append(data)
    def handle_starttag(self, tag, attrs):
        if tag=='a': self.links.append(dict(attrs))


class ButtonLabelTests(unittest.TestCase):
    def normalize(self, ape): return normalize_button_labels(ape, VALIDATE)

    def test_observed_span_font_size_line_height_and_strong_preserve_exact_label(self):
        labels=['<span style="font-size: 18px;">Audio 1</span>',
                '<span style="font-size: 16px; line-height: 1.5;">Audio 2</span>',
                '<strong>Presentation &amp; notes</strong>',
                '<span>First<br>second <strong>part</strong></span>']
        original=page(*(button(label) for label in labels)); saved=copy.deepcopy(original)
        out,changes=self.normalize(original)
        self.assertEqual(original,saved)
        self.assertEqual(changes,[{'path':[i],'code':CODE} for i in range(len(labels))])
        for label,node,before in zip(labels,out['children'],original['children']):
            self.assertEqual(node['name'],'text'); self.assertEqual(set(node['fields']),{'html'})
            self.assertEqual(node['fields']['html'],'<p><a href="https://example.test/material?first=1&amp;second=2">'+label+'</a></p>')
            self.assertEqual(node['id'],before['id']); self.assertEqual(node['style'],before['style'])
            self.assertEqual(node['children'],[]); VALIDATE(node['fields']['html'])
            old,new=Contents(),Contents(); old.feed(label);new.feed(node['fields']['html'])
            self.assertEqual(new.text,old.text); self.assertEqual(new.links,[{'href':URL}])

    def test_url_trim_escape_and_explicit_new_window_are_preserved(self):
        label='<b>Material &amp; recording</b>'; url='https://example.test/file?name="x"&next=1'
        out,changes=self.normalize(page(button(label,url=' \t'+url+'\r\n',blank=True)))
        markup=out['children'][0]['fields']['html']; parsed=Contents();parsed.feed(markup)
        self.assertIn(label,markup);self.assertEqual(parsed.links,[{'href':url,'target':'_blank','rel':'noopener noreferrer'}])
        self.assertEqual(len(changes),1); VALIDATE(markup)

    def test_order_nested_paths_plain_buttons_and_second_pass_unchanged(self):
        ape=page(button('Plain label'),{'name':'section','children':[button(),{'name':'text','fields':{'html':'Keep following text'}}]})
        out,changes=self.normalize(ape)
        self.assertEqual(out['children'][0],ape['children'][0]);self.assertEqual(changes,[{'path':[1,0],'code':CODE}])
        self.assertEqual(out['children'][1]['children'][1],ape['children'][1]['children'][1])
        again,next_changes=self.normalize(out);self.assertEqual(again,out);self.assertEqual(next_changes,[])

    def test_already_supported_br_only_labels_keep_fingerprint_and_core_output(self):
        for label in ('First<br>second','First<BR />second','First<br/>second'):
            original={'account':'mastervision','source_origin':'https://shop.mastervision.su',
                      'course_id':1,'lesson_id':4,'course_title':'Synthetic course',
                      'lesson_title':'Synthetic lesson','format':'ape','ape':page(button(label))}
            original['ape']['children'][0].pop('style')
            before=json.dumps(original,sort_keys=True,separators=(',',':'))
            converted,changes=self.normalize(original['ape'])
            after=copy.deepcopy(original);after['ape']=converted
            self.assertEqual(changes,[])
            self.assertEqual(json.dumps(after,sort_keys=True,separators=(',',':')),before)
            self.assertEqual(_core().plan_import(after),_core().plan_import(original))
            self.assertTrue(_core().plan_import(after)['ready'])

    def test_unknown_or_meaningful_native_settings_are_not_reinterpreted(self):
        cases=[button(linkType='anchor'),button(anchor='part'),button(icon='download'),
               button(icon={}),button(toAnchor='part'),button(event='submit'),button(unknown=None),
               button(unknown='setting'),button(blank='false')]
        nested=button();nested['children']=[{'name':'text','fields':{'html':'Keep child'}}];cases.append(nested)
        for node in cases:
            with self.subTest(fields=list(node['fields'])):
                ape=page(node);out,changes=self.normalize(ape);self.assertEqual(out,ape);self.assertEqual(changes,[])

    def test_invalid_or_missing_url_is_never_removed_or_guessed(self):
        for url in ('',None,'{goods_ordering_123}','javascript:alert(1)','https://example.test/a https://example.test/b',
                    'https://user:secret@example.test/a','https://example.test/a\\b'):
            ape=page(button(url=url));out,changes=self.normalize(ape);self.assertEqual(out,ape);self.assertEqual(changes,[])

    def test_unsafe_nested_link_active_and_noninline_labels_are_unchanged(self):
        labels=['<a href="https://example.test/other">Link</a>','<script>bad()</script>',
                '<img src="https://example.test/a.png">','<iframe src="https://example.test/"></iframe>',
                '<span onclick="bad()">Audio</span>','<span style="background:url(https://example.test/a)">Audio</span>',
                '<span style="color:red" style="color:blue">Audio</span>','<strong>Unclosed',
                '<p>Block label</p>','<span><!--comment-->Audio</span>','<span>&nbsp;<br></span>',None,7]
        for label in labels:
            with self.subTest(label_type=type(label).__name__):
                ape=page(button(label));out,changes=self.normalize(ape);self.assertEqual(out,ape);self.assertEqual(changes,[])

    def test_trainer_actions_remain_for_existing_global_omission(self):
        for label in ('<strong>Задать вопрос тренеру</strong>','<span>Вопрос тренеру здесь</span>'):
            ape=page(button(label));out,changes=self.normalize(ape);self.assertEqual(out,ape);self.assertEqual(changes,[])

    def test_validator_refusal_leaves_exact_button_and_diagnostic_is_metadata_only(self):
        def refuse(markup): raise ValueError('unsupported_style')
        ape=page(button());out,changes=normalize_button_labels(ape,refuse)
        self.assertEqual(out,ape);self.assertEqual(changes,[])
        _,changes=self.normalize(ape)
        self.assertEqual(set(changes[0]),{'path','code'});self.assertNotIn('http',str(changes))

    def test_actual_core_gate_is_cleared_and_new_window_html_reaches_plan_intact(self):
        for blank in (False,True):
            original={'account':'mastervision','source_origin':'https://shop.mastervision.su',
                      'course_id':1,'lesson_id':4,'course_title':'Synthetic course',
                      'lesson_title':'Synthetic lesson','format':'ape','ape':page(button(blank=blank))}
            original['ape']['children'][0].pop('style')
            before=_core().plan_import(original)
            self.assertIn('unsupported_button',before['issues']);self.assertFalse(before['ready'])
            prepared=copy.deepcopy(original);prepared['ape'],_=self.normalize(original['ape'])
            after=_core().plan_import(prepared)
            self.assertTrue(after['ready'],after['issues']);self.assertEqual(len(after['blocks']),1)
            block=after['blocks'][0]
            markup=(base64.b64decode(block['data']['encodedHtml']).decode('utf-8')
                    if block['type']=='htmlBlock' else block['data']['text'])
            parsed=Contents();parsed.feed(markup)
            self.assertEqual(parsed.links[0]['href'],URL);self.assertEqual(parsed.text,['Audio'])
            if blank:
                self.assertEqual(block['type'],'htmlBlock')
                self.assertIn('<span style="font-size: 18px;">Audio</span>',markup)
                self.assertEqual(parsed.links[0]['target'],'_blank')

    def test_invalid_tree_and_validator_fail_with_fixed_review(self):
        for ape in (None,[],{'name':'text','children':[]},page('unknown'),page({'name':'button','fields':[]})):
            with self.assertRaises(Review): self.normalize(ape)
        with self.assertRaisesRegex(Review,'button_labels_validator_invalid'):
            normalize_button_labels(page(),None)

    def test_only_known_null_display_fields_allow_formatted_material_link(self):
        original=page(button('<span style="font-size: 16px;">Podcast recording</span>',
                             displayDelay=None,visibleConditions=None))
        before=copy.deepcopy(original);out,changes=self.normalize(original)
        expected,_=self.normalize(page(button('<span style="font-size: 16px;">Podcast recording</span>')))
        self.assertEqual(original,before);self.assertEqual(out,expected)
        self.assertEqual(changes,[{'path':[0],'code':CODE}])
        markup=out['children'][0]['fields']['html'];parsed=Contents();parsed.feed(markup)
        self.assertEqual(parsed.links[0]['href'],URL);self.assertEqual(parsed.text,['Podcast recording'])

    def test_nonnull_condition_and_delay_values_are_never_consumed(self):
        for key in ('displayDelay','visibleConditions'):
            for value in (0,False,'',[],{},1,{'purchase':'required'}):
                source=page(button(**{key:value}));out,changes=self.normalize(source)
                with self.subTest(key=key,value_type=type(value).__name__):
                    self.assertEqual((out,changes),(source,[]))

    def test_plain_and_br_only_buttons_with_null_fields_keep_accepted_fingerprints(self):
        for label in ('Podcast','First<br>second'):
            original={'account':'mastervision','source_origin':'https://shop.mastervision.su',
                      'course_id':1,'lesson_id':4,'course_title':'Synthetic course','lesson_title':'Synthetic lesson',
                      'format':'ape','ape':page(button(label,displayDelay=None,visibleConditions=None))}
            before=json.dumps(original,sort_keys=True,separators=(',',':'))
            ape,changes=self.normalize(original['ape']);after=copy.deepcopy(original);after['ape']=ape
            self.assertEqual(changes,[]);self.assertEqual(json.dumps(after,sort_keys=True,separators=(',',':')),before)
            self.assertEqual(_core().plan_import(after),_core().plan_import(original))


if __name__=='__main__': unittest.main()

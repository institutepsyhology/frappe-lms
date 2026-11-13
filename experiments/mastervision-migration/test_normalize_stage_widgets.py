"""Synthetic template fixtures exercise the strict nonexecuting widget policy."""
import copy
import hashlib
from html import escape
from html.parser import HTMLParser
import importlib.util
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from importer import Review
import normalize_stage_widgets as widgets
from normalize_editor_nodes import _core

spec=importlib.util.spec_from_file_location('stage_test_static',Path(__file__).resolve().parents[2]/'lms/lms/avo_html_fragment.py')
static=importlib.util.module_from_spec(spec);spec.loader.exec_module(static)
VALIDATE=static.make_html_block
SCRIPT="const p = wrapper.getAttribute('data-progress'); progressBar.style.width = p + '%';"
CSS='.progress-wrapper { position: relative; }'
WRAPPER_STYLE='position: relative;'
BAR_STYLE='width: 0%;'
LABEL_STYLE='color: white;'


def sha(value):return hashlib.sha256(value.encode('utf-8')).hexdigest()
def canonical(value):return json.dumps(value,ensure_ascii=True,sort_keys=True,separators=(',',':'))
EXPECTED_DOM=[{'tag':'div','attrs':{'class':'progress-wrapper','style':WRAPPER_STYLE,'data-progress':'@progress'},
               'children':[{'tag':'div','attrs':{'class':'progress-bar','style':BAR_STYLE},'children':[]},
                           {'tag':'div','attrs':{'style':LABEL_STYLE},'children':['@label']}]},
              {'tag':'style','attrs':{},'children':[{'sha256':sha(CSS)}]},
              {'tag':'script','attrs':{},'children':[{'sha256':sha(SCRIPT)}]}]


def markup(label='Course stage',progress='14'):
    return ('<div class="progress-wrapper" style="'+WRAPPER_STYLE+'" data-progress="'+progress+'">\n'
            '<div class="progress-bar" style="'+BAR_STYLE+'"></div>\n'
            '<div style="'+LABEL_STYLE+'">'+escape(label)+'</div></div>\n'
            '<style>'+CSS+'</style>\n<script>'+SCRIPT+'</script>')


def widget(html=None,**fields):
    return {'id':'stage-widget','name':'code','fields':{'anchor':'','html':markup() if html is None else html,**fields},
            'style':{'spacing':{'margin':'8px'}},'children':[]}
def page(*nodes):return {'name':'page','children':list(nodes)}


class Text(HTMLParser):
    def __init__(self):super().__init__(convert_charrefs=True);self.parts=[]
    def handle_data(self,value):self.parts.append(value)


class StageWidgetTests(unittest.TestCase):
    def setUp(self):
        # Public tests register only this synthetic template. Production hashes
        # are separately checked against all private captures, never copied here.
        self.policy=patch.multiple(widgets,DOM_SHA256=sha(canonical(EXPECTED_DOM)),
            SCRIPT_SHA256=sha(SCRIPT),STYLESHEET_SHA256=sha(CSS))
        self.policy.start();self.addCleanup(self.policy.stop)

    def normalize(self,ape):return widgets.normalize_stage_widgets(ape,VALIDATE)

    def test_caption_percentage_identity_style_and_original_source_are_preserved(self):
        label='ЗНАКОМСТВО {name} & "notes"';source=page(widget(markup(label,'14')));before=copy.deepcopy(source)
        out,changes=self.normalize(source);node=out['children'][0]
        self.assertEqual(source,before);self.assertEqual(node['name'],'text')
        self.assertEqual(node['id'],'stage-widget');self.assertEqual(node['style'],before['children'][0]['style'])
        self.assertEqual(node['children'],[])
        self.assertEqual(node['fields'],{'html':'<p><strong>'+escape(label)+'</strong> · 14%</p>'})
        self.assertEqual(changes,[{'path':[0],'code':'static_course_stage_preserved'}])
        parser=Text();parser.feed(node['fields']['html']);self.assertEqual(''.join(parser.parts),label+' · 14%')
        VALIDATE(node['fields']['html'])

    def test_source_numbers_are_bounded_and_preserved_without_relabeling_student_progress(self):
        for value in ('0','100','14.25','01.50'):
            out,changes=self.normalize(page(widget(markup('Stage',value))))
            self.assertEqual(out['children'][0]['fields']['html'],'<p><strong>Stage</strong> · '+value+'%</p>')
            self.assertEqual(len(changes),1)
        for value in ('-1','101','100.01','NaN','Infinity','1e2','14%',' 14 ',''):
            source=page(widget(markup('Stage',value)));self.assertEqual(self.normalize(source),(source,[]))

    def test_unknown_or_added_scripts_and_changed_css_are_never_enabled(self):
        for html in (markup().replace(SCRIPT,SCRIPT+'alert(1);'),markup()+'<script>'+SCRIPT+'</script>',
                     markup().replace(CSS,CSS+' .other { display: none; }'),markup().replace('<script>','<script src="https://example.test/code.js">')):
            source=page(widget(html));self.assertEqual(self.normalize(source),(source,[]))

    def test_extra_urls_purchase_links_actions_and_dom_attributes_are_refused(self):
        for html in (markup()+'<a href="https://example.test/order">Buy</a>',
                     markup().replace('class="progress-wrapper"','class="progress-wrapper" onclick="buy()"'),
                     markup().replace('class="progress-bar"','class="progress-bar other"'),
                     markup().replace('class="progress-bar"','class="progress-bar" data-order="42"'),
                     markup().replace('position: relative;','background-image: url(https://example.test/image);'),
                     markup()+'<img src="https://example.test/photo.jpg">'):
            source=page(widget(html));self.assertEqual(self.normalize(source),(source,[]))

    def test_ape_conditions_anchor_children_unknown_fields_and_style_media_are_protected(self):
        sources=[widget(anchor='section'),widget(visibleConditions=None),widget(visibleConditions={'paid':True}),
                 widget(callback='buy'),widget(unknown=None)]
        child=widget();child['children']=[widget()];sources.append(child)
        styled=widget();styled['style']={'backgroundImage':{'url':'https://example.test/photo.jpg'}};sources.append(styled)
        for node in sources:
            source=page(node);self.assertEqual(self.normalize(source),(source,[]))
        conditional={'name':'container','fields':{'visibleConditions':{'paid':True}},'children':[widget()]}
        self.assertEqual(self.normalize(page(conditional)),(page(conditional),[]))

    def test_plain_text_caption_is_escaped_and_nested_caption_markup_is_refused(self):
        label='<script>literal & safe</script>'
        out,changes=self.normalize(page(widget(markup(label))))
        self.assertIn(escape(label),out['children'][0]['fields']['html']);self.assertEqual(len(changes),1)
        for html in (markup().replace('Course stage','<strong>Course stage</strong>'),
                     markup().replace('Course stage',''),markup()+'<!--unknown-->'):
            source=page(widget(html));self.assertEqual(self.normalize(source),(source,[]))

    def test_scripts_are_not_executed_and_no_source_script_survives_in_output(self):
        with patch('builtins.eval',side_effect=AssertionError('source_eval_forbidden')) as evaluate:
            out,_=self.normalize(page(widget()))
        evaluate.assert_not_called();result=json.dumps(out)
        self.assertNotIn(SCRIPT,result);self.assertNotIn('<script',result);self.assertNotIn('<style',result)

    def test_order_paths_and_second_pass_are_stable(self):
        before={'name':'text','fields':{'html':'Before'}};after={'name':'text','fields':{'html':'After'}}
        source=page(before,{'name':'container','children':[widget()]},after)
        out,changes=self.normalize(source)
        self.assertEqual(out['children'][0],before);self.assertEqual(out['children'][2],after)
        self.assertEqual(changes,[{'path':[1,0],'code':widgets.CODE}])
        repeated,next_changes=self.normalize(out);self.assertEqual(repeated,out);self.assertEqual(next_changes,[])

    def test_actual_core_unknown_code_becomes_ready_static_lesson_with_both_values(self):
        source={'account':'mastervision','source_origin':'https://shop.mastervision.su','course_id':1,
                'lesson_id':4,'course_title':'Synthetic','lesson_title':'Synthetic','format':'ape','ape':page(widget())}
        self.assertIn('unknown_block',_core().plan_import(source)['issues'])
        prepared=copy.deepcopy(source);prepared['ape'],_=self.normalize(source['ape'])
        plan=_core().plan_import(prepared);self.assertTrue(plan['ready'],plan['issues'])
        self.assertEqual(plan['blocks'],[{'type':'paragraph','data':{'text':'<p><strong>Course stage</strong> · 14%</p>'}}])

    def test_validator_refusal_and_non_widget_code_keep_original_fingerprint(self):
        def refuse(value):raise ValueError('unsupported_html')
        source=page(widget());self.assertEqual(widgets.normalize_stage_widgets(source,refuse),(source,[]))
        plain=page(widget('<p>Ordinary code</p>'));out,changes=self.normalize(plain)
        self.assertEqual(canonical(out),canonical(plain));self.assertEqual(changes,[])

    def test_malformed_markup_tree_or_validator_are_handled_without_source_execution(self):
        for html in (markup().replace('</div>','',1),markup()+'<!DOCTYPE html>',markup()+'<?process no?>'):
            source=page(widget(html));self.assertEqual(self.normalize(source),(source,[]))
        for source in (None,[],{'name':'text','children':[]},page('invalid'),page({'name':'code','fields':[]})):
            with self.assertRaises(Review):self.normalize(source)
        with self.assertRaisesRegex(Review,'stage_widgets_validator_invalid'):
            widgets.normalize_stage_widgets(page(),None)


if __name__=='__main__':unittest.main()

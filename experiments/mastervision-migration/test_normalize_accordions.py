"""Accordion regressions preserve visible lesson content without source scripts."""
import copy
import importlib.util
import json
from pathlib import Path
import re
import unittest

from importer import Review
from normalize_accordions import CODE, normalize_accordions
from normalize_editor_nodes import _core

spec=importlib.util.spec_from_file_location('accordion_test_static',Path(__file__).resolve().parents[2]/'lms/lms/avo_html_fragment.py')
static=importlib.util.module_from_spec(spec);spec.loader.exec_module(static)
VALIDATE=static.make_html_block


def text(value): return {'name':'text','fields':{'html':value},'children':[]}
def item(header='<strong>Materials</strong>',*children,**fields):
    return {'id':'item-id','name':'unfolding-item','fields':{'headerHtml':header,**fields},
            'style':{'spacing':{'margin':'8px'}},'children':list(children)}
def accordion(*items,**fields):
    return {'id':'accordion-id','name':'unfolding','fields':{'initialState':'all-folded',
        'expandedSpeedRate':1,'onlyOneExpanded':True,**fields},'children':list(items)}
def page(*nodes): return {'name':'page','children':list(nodes)}
def walk(node):
    yield node
    for child in node.get('children',[]): yield from walk(child)


class AccordionTests(unittest.TestCase):
    def normalize(self,ape): return normalize_accordions(ape,VALIDATE)

    def test_observed_parent_fields_and_exact_header_before_untouched_children(self):
        source=page(accordion(item('<strong>Audio &amp; notes</strong>',text('<p>First {name}</p>'),text('Second')),
                              anchor='',visibleConditions=None))
        before=copy.deepcopy(source);out,changes=self.normalize(source)
        self.assertEqual(source,before)
        parent=out['children'][0];child=parent['children'][0]
        self.assertEqual(parent['name'],'container');self.assertEqual(parent['id'],'accordion-id');self.assertEqual(parent['fields'],{})
        self.assertEqual(child['name'],'container');self.assertEqual(child['id'],'item-id')
        self.assertEqual(child['style'],before['children'][0]['children'][0]['style'])
        self.assertEqual(child['fields'],{})
        self.assertEqual(child['children'][0]['fields'],{'html':'<strong>Audio &amp; notes</strong>'})
        self.assertEqual(child['children'][1:],before['children'][0]['children'][0]['children'])
        self.assertEqual(changes,[{'path':[0],'code':CODE},{'path':[0,0],'code':CODE}])

    def test_multiple_items_nested_accordions_links_and_media_order_are_conserved(self):
        image={'id':'photo','name':'image','fields':{'imageSrc':'https://example.test/photo.jpg'}}
        video={'id':'video','name':'video','fields':{'videoProvider':'youtube','videoSrc':'https://youtu.be/abcdefghijk'}}
        button={'id':'download','name':'button','fields':{'html':'Audio','linkType':'url','url':'https://example.test/audio.mp3'}}
        source=page(text('Before'),accordion(item('First',image,button),item('<a href="https://example.test/notes">Second</a>',
                    video,accordion(item('Nested',text('Last'))))),text('After'))
        out,changes=self.normalize(source)
        material=[n for n in walk(out) if n.get('name') in('image','video','button')]
        self.assertEqual(material,[image,button,video])
        captions=[n['fields']['html'] for n in walk(out) if n.get('name')=='text']
        self.assertEqual(captions,['Before','First','<a href="https://example.test/notes">Second</a>','Nested','Last','After'])
        self.assertEqual(len(changes),5)

    def test_generated_header_ids_are_valid_deterministic_unique_and_collision_checked(self):
        source=page(accordion(item('Same',text('A')),item('Same',text('B'))))
        first,_=self.normalize(source)
        generated=[n['id'] for n in walk(first) if n.get('name')=='text' and n['fields']['html']=='Same']
        self.assertEqual(len(set(generated)),2)
        self.assertTrue(all(re.fullmatch(r'[A-Za-z0-9_-]{1,80}',ident) for ident in generated))
        repeated,_=self.normalize(source);self.assertEqual(repeated,first)
        collision=text('Existing');collision['id']=generated[0];source['children'].append(collision)
        out,_=self.normalize(source)
        new=[n['id'] for n in walk(out) if n.get('name')=='text' and n['fields']['html']=='Same']
        self.assertNotIn(generated[0],new);self.assertEqual(out['children'][-1],collision)
        self.assertEqual(self.normalize(source)[0],out)

    def test_meaningful_conditions_actions_and_unrecognized_settings_protect_whole_subtree(self):
        cases=[{'anchor':'important'},{'visibleConditions':{'paid':True}},{'callback':'open'},
               {'unknown':None},{'initialState':'custom'},{'expandedSpeedRate':'1'},
               {'expandedSpeedRate':2},{'onlyOneExpanded':False}]
        for fields in cases:
            with self.subTest(fields=list(fields)):
                source=page(accordion(item('Keep',accordion(item('Nested',text('Private content')))),**fields))
                out,changes=self.normalize(source);self.assertEqual(out,source);self.assertEqual(changes,[])

    def test_unknown_item_settings_and_unsafe_header_do_not_change_its_subtree(self):
        for header,fields in [('<script>bad()</script>',{}),('<img src="https://example.test/image.png">',{}),
                              ('<strong onclick="bad()">Title</strong>',{}),('<strong>Unclosed',{}),('',{}),(None,{}),
                              ('Keep',{'visibleConditions':{'paid':True}}),('Keep',{'callback':'open'}),('Keep',{'unknown':None})]:
            source=page(item(header,accordion(item('Nested',text('Content'))),**fields))
            out,changes=self.normalize(source);self.assertEqual(out,source);self.assertEqual(changes,[])

    def test_meaningful_style_media_or_node_metadata_is_not_flattened(self):
        for extra in ({'style':{'backgroundImage':{'value':{'url':'https://example.test/important.png'}}}},
                      {'style':{'content':{'value':'Meaningful material'}}},{'callback':'open'}):
            node=accordion(item('Keep',text('Content')));node.update(extra);source=page(node)
            out,changes=self.normalize(source);self.assertEqual(out,source);self.assertEqual(changes,[])

    def test_existing_structure_and_second_pass_keep_exact_fingerprint(self):
        plain=page(text('Ordinary text'),{'name':'container','children':[text('Child')]})
        out,changes=self.normalize(plain);self.assertEqual(out,plain);self.assertEqual(changes,[])
        out,_=self.normalize(page(accordion(item('Heading',text('Body')))))
        fingerprint=json.dumps(out,sort_keys=True,separators=(',',':'))
        again,changes=self.normalize(out);self.assertEqual(changes,[])
        self.assertEqual(json.dumps(again,sort_keys=True,separators=(',',':')),fingerprint)

    def test_real_core_unknown_block_gate_clears_without_losing_header_or_body(self):
        source={'account':'mastervision','source_origin':'https://shop.mastervision.su','course_id':1,
                'lesson_id':4,'course_title':'Synthetic','lesson_title':'Synthetic','format':'ape',
                'ape':page(accordion(item('<b>Header</b>',text('<p>Body {name}</p>'))))}
        before=_core().plan_import(source);self.assertIn('unknown_block',before['issues'])
        prepared=copy.deepcopy(source);prepared['ape'],_=self.normalize(source['ape'])
        after=_core().plan_import(prepared);self.assertTrue(after['ready'],after['issues'])
        self.assertEqual([b['data']['text'] for b in after['blocks']],['<b>Header</b>','<p>Body {name}</p>'])

    def test_validator_refusal_leaves_exact_tree_and_changes_are_metadata_only(self):
        def refuse(markup): raise ValueError('unsupported_html')
        source=page(item('Heading',text('Body')))
        self.assertEqual(normalize_accordions(source,refuse),(source,[]))
        _,changes=self.normalize(source)
        self.assertTrue(all(set(change)=={'path','code'} for change in changes))
        self.assertNotIn('Heading',str(changes));self.assertNotIn('http',str(changes))

    def test_invalid_tree_or_validator_reports_fixed_review(self):
        for source in (None,[],{'name':'text','children':[]},page('invalid'),page({'name':'text','fields':[]})):
            with self.assertRaises(Review):self.normalize(source)
        with self.assertRaisesRegex(Review,'accordions_validator_invalid'):
            normalize_accordions(page(),None)


if __name__=='__main__':unittest.main()

"""Synthetic annotated-link fixtures; never include production addresses/content."""
import copy
import json
import unittest
from unittest.mock import patch

from importer import Review
from normalize_editor_nodes import _core
from normalize_source import static_validator
import normalize_annotated_material_buttons as mod

FIRST = 'https://disk.yandex.ru/d/synthetic_audio'
SECOND = 'https://disk.yandex.ru/i/synthetic_presentation'
DRIVE = 'https://drive.google.com/file/d/synthetic_file/view?usp=sharing'


def button(url=None, **fields):
    return {'id':'annotated','name':'button','fields':{
        'anchor':'','html':'АУДИОЗАПИСЬ','icon':'','linkType':'url','url':url if url is not None else FIRST+mod.ANNOTATION+SECOND,
        'blank':True,'toAnchor':'','event':'',**fields},'children':[], 'style':{'padding':'12px'}}


def page(*nodes): return {'name':'page','children':list(nodes)}


class AnnotatedMaterialTests(unittest.TestCase):
    def normalize(self, ape, scope=(326,5253)):
        return mod.normalize_annotated_material_buttons(ape,static_validator(),*scope)

    def test_both_explicit_urls_labels_and_duplicate_neighbour_are_preserved(self):
        neighbour=button(FIRST,html='ПРЕЗЕНТАЦИЯ');neighbour['id']='existing'
        ape=page(neighbour,button(),{'name':'text','fields':{'html':'<p>After.</p>'}});before=copy.deepcopy(ape)
        out,changes=self.normalize(ape);node=out['children'][1]
        self.assertEqual(ape,before);self.assertEqual(out['children'][0],neighbour)
        self.assertEqual(out['children'][2],ape['children'][2])
        self.assertEqual((node['id'],node['style'],node['children']),('annotated',ape['children'][1]['style'],[]))
        parser=mod._Content();parser.feed(node['fields']['html'])
        self.assertEqual(parser.links,[FIRST,SECOND]);self.assertEqual(''.join(parser.parts),'АУДИОЗАПИСЬ'+mod.ANNOTATION)
        self.assertEqual(changes[0]['form'],'two_material_links');self.assertEqual(changes[0]['links'],2)
        self.assertEqual(changes[0]['path'],[1]);self.assertNotIn('https://',json.dumps(changes))

    def test_drive_prefix_and_exact_formatted_audio_label_are_preserved(self):
        label='<strong>АУДИОЗАПИСЬ</strong>'
        ape=page(button(mod.PREFIX+DRIVE,html=label));out,changes=self.normalize(ape,(525,5302))
        html=out['children'][0]['fields']['html']
        self.assertIn(label,html);parser=mod._Content();parser.feed(html)
        self.assertEqual(parser.links,[DRIVE]);self.assertEqual(''.join(parser.parts),mod.PREFIX+'АУДИОЗАПИСЬ')
        self.assertIn('target="_blank" rel="noopener noreferrer"',html)
        self.assertEqual(changes[0]['form'],'video_material_note')

    def test_false_blank_and_null_visibility_do_not_create_actions_or_discard_content(self):
        ape=page(button(blank=False,visibleConditions=None,displayDelay=None))
        out,changes=self.normalize(ape);self.assertEqual(len(changes),1)
        self.assertNotIn('target=',out['children'][0]['fields']['html'])

    def test_replay_is_deterministic_and_already_normalized_nodes_are_exact_noops(self):
        ape=page(button());before=copy.deepcopy(ape);out,changes=self.normalize(ape)
        self.assertEqual(self.normalize(ape),(out,changes));self.assertEqual(self.normalize(out),(out,[]))
        self.assertEqual(ape,before)

    def test_only_exact_two_scopes_are_authorized(self):
        ape=page(button())
        for scope in ((325,5253),(326,5254),(525,5253),(1,1)):
            self.assertEqual(self.normalize(ape,scope),(ape,[]))
        for scope in ((True,5253),(326,'5253'),(0,1)):
            with self.assertRaises(Review):self.normalize(ape,scope)
        with patch.object(mod,'ACCOUNT','mv-centr'),self.assertRaises(Review):self.normalize(ape)

    def test_grammar_cardinality_and_routes_never_guess_a_link(self):
        invalid=[FIRST+' Презентация: '+SECOND,FIRST+mod.ANNOTATION+SECOND+' ',
                 FIRST+mod.ANNOTATION+SECOND+' https://disk.yandex.ru/d/third',
                 FIRST+mod.ANNOTATION, FIRST, 'prefix '+FIRST+mod.ANNOTATION+SECOND,
                 FIRST.replace('https:','http:')+mod.ANNOTATION+SECOND,
                 FIRST.replace('disk.yandex.ru','other.test')+mod.ANNOTATION+SECOND,
                 FIRST+'?key=unknown'+mod.ANNOTATION+SECOND,
                 FIRST+'#hidden'+mod.ANNOTATION+SECOND,
                 FIRST.replace('disk.yandex.ru','user@disk.yandex.ru')+mod.ANNOTATION+SECOND]
        for url in invalid:
            ape=page(button(url));self.assertEqual(self.normalize(ape),(ape,[]))
        for url in ('ко 1 видео '+DRIVE,mod.PREFIX+DRIVE+' suffix',mod.PREFIX+DRIVE+'&unknown=1',
                    mod.PREFIX+DRIVE.replace('/view','/preview'),mod.PREFIX+'javascript:private()'):
            ape=page(button(url));self.assertEqual(self.normalize(ape,(525,5302)),(ape,[]))

    def test_unknown_settings_actions_children_and_material_styles_are_unchanged(self):
        for fields in ({'anchor':'keep'},{'icon':'keep'},{'event':'submit'},{'toAnchor':'lesson'},
                       {'linkType':'event'},{'blank':1},{'unknown':None},{'visibleConditions':False},
                       {'visibleConditions':{'active':True}},{'displayDelay':3}):
            ape=page(button(**fields));self.assertEqual(self.normalize(ape),(ape,[]))
        for key,value in (('extra',None),('children',[{'name':'text','fields':{'html':'Keep'}}]),
                          ('style',{'caption':'Keep'})):
            node=button();node[key]=value;ape=page(node);self.assertEqual(self.normalize(ape),(ape,[]))
        node=button();del node['fields']['icon'];ape=page(node);self.assertEqual(self.normalize(ape),(ape,[]))
        ape=page(button());ape['fields']={'visibleConditions':{'active':True}}
        self.assertEqual(self.normalize(ape),(ape,[]))

    def test_unknown_labels_unsafe_markup_and_validator_refusal_keep_original(self):
        for label in ('Unknown material','АУДИОЗАПИСЬ<script>private()</script>',
                      '<a href="https://example.test/">АУДИОЗАПИСЬ</a>',
                      '<span onclick="private()">АУДИОЗАПИСЬ</span>','<strong>АУДИОЗАПИСЬ'):
            ape=page(button(html=label));self.assertEqual(self.normalize(ape),(ape,[]))
        ape=page(button())
        def reject(_):raise ValueError('refused')
        self.assertEqual(mod.normalize_annotated_material_buttons(ape,reject,326,5253),(ape,[]))

    def test_multiple_matching_candidates_are_ambiguous_and_input_is_unchanged(self):
        ape=page(button(),button());before=copy.deepcopy(ape)
        with self.assertRaisesRegex(Review,'annotated_material_button_ambiguous'):self.normalize(ape)
        self.assertEqual(ape,before)

    def test_real_core_accepts_preserved_material_for_both_forms(self):
        for scope,node in (((326,5253),button()),((525,5302),button(mod.PREFIX+DRIVE))):
            payload={'account':'mastervision','source_origin':'https://shop.mastervision.su',
                     'course_id':scope[0],'lesson_id':scope[1],'course_title':'Synthetic','lesson_title':'Synthetic',
                     'format':'ape','ape':page(node)}
            self.assertIn('unsupported_button',_core().plan_import(payload)['issues'])
            out,changes=self.normalize(payload['ape'],scope);converted=copy.deepcopy(payload);converted['ape']=out
            plan=_core().plan_import(converted);self.assertTrue(plan['ready']);self.assertEqual(plan['issues'],[])

    def test_invalid_api_uses_fixed_diagnostics(self):
        for ape in ([],{},page(None)):
            with self.assertRaises(Review):self.normalize(ape)
        with self.assertRaises(Review):mod.normalize_annotated_material_buttons(page(button()),None,326,5253)


if __name__=='__main__':unittest.main()

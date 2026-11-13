"""Known invisible editor labels must not become visible lesson captions."""
import copy
import json
import unittest
from unittest.mock import patch

from importer import Review
import normalize_image_labels as labels
from normalize_editor_nodes import _core

URL='https://example.test/photo.jpg'


def image(**fields):
    return {'id':'photo','name':'image','fields':{'anchor':'','imageSrc':URL,'html':'Изображение',**fields},
            'style':{'lists':{'image':{'width':{'value':{'value':300,'unit':'px'}}}}}}
def page(*nodes):return {'name':'page','children':list(nodes)}
def validate(value):raise AssertionError('No new HTML should be generated')


class ImageLabelTests(unittest.TestCase):
    def normalize(self,ape):return labels.normalize_image_labels(ape,validate)

    def test_exact_invisible_field_is_consumed_without_other_changes(self):
        source=page(image());before=copy.deepcopy(source);out,changes=self.normalize(source)
        expected=copy.deepcopy(source);del expected['children'][0]['fields']['html']
        self.assertEqual(source,before);self.assertEqual(out,expected)
        self.assertEqual(changes,[{'path':[0],'code':labels.CODE}])

    def test_image_identity_style_source_url_and_empty_children_are_preserved(self):
        node=image();node['children']=[];source=page(node);out,_=self.normalize(source)
        for key in ('id','name','style','children'):self.assertEqual(out['children'][0][key],node[key])
        self.assertEqual(out['children'][0]['fields']['imageSrc'],URL)

    def test_no_caption_container_or_extra_node_is_created(self):
        source=page(image());out,_=self.normalize(source)
        self.assertEqual(len(out['children']),1);self.assertEqual(out['children'][0]['name'],'image')
        self.assertNotIn('Изображение',json.dumps(out,ensure_ascii=False))

    def test_actual_visible_or_formatted_captions_are_not_removed(self):
        for value in ('A real caption','Изображение ',' изображение','<p>Изображение</p>','<b>Изображение</b>',
                      '<script>bad()</script>'):
            source=page(image(html=value));self.assertEqual(self.normalize(source),(source,[]))

    def test_already_ready_images_keep_exact_fingerprint(self):
        for value in (None,'',False):
            source=page(image(html=value));before=json.dumps(source,sort_keys=True)
            out,changes=self.normalize(source);self.assertEqual(changes,[]);self.assertEqual(json.dumps(out,sort_keys=True),before)
        source=page(image());del source['children'][0]['fields']['html']
        self.assertEqual(self.normalize(source),(source,[]))

    def test_plain_text_header_and_code_nodes_with_same_word_are_untouched(self):
        for kind in ('text','header','code','button'):
            node=image();node['name']=kind;source=page(node)
            self.assertEqual(self.normalize(source),(source,[]))

    def test_meaningful_anchor_or_image_link_is_protected(self):
        for fields in ({'anchor':'bookmark'},{'linkHref':'https://example.test/download'},
                       {'caption':'Keep this caption'},{'visibleConditions':{'paid':True}}):
            source=page(image(**fields));self.assertEqual(self.normalize(source),(source,[]))

    def test_known_empty_optional_link_is_safe(self):
        source=page(image(linkHref=''));out,changes=self.normalize(source)
        self.assertEqual(out['children'][0]['fields']['linkHref'],'');self.assertEqual(len(changes),1)

    def test_unknown_field_or_node_metadata_even_empty_is_preserved(self):
        for key,value in (('unknown',None),('linkTarget','_blank'),('callback','open')):
            source=page(image(**{key:value}));self.assertEqual(self.normalize(source),(source,[]))
        node=image();node['callback']=None;source=page(node)
        self.assertEqual(self.normalize(source),(source,[]))

    def test_children_and_media_or_text_inside_style_are_not_discarded(self):
        node=image();node['children']=[{'name':'text','fields':{'html':'Child'}}];source=page(node)
        self.assertEqual(self.normalize(source),(source,[]))
        for style in ({'backgroundImage':{'url':'https://example.test/other.jpg'}},
                      {'content':{'value':'Visible material'}},['unknown']):
            node=image();node['style']=style;source=page(node);self.assertEqual(self.normalize(source),(source,[]))

    def test_inherited_visibility_conditions_protect_subtree(self):
        source=page({'name':'container','fields':{'visibleConditions':{'paid':True}},'children':[image()]})
        self.assertEqual(self.normalize(source),(source,[]))

    def test_missing_invalid_relative_and_placeholder_image_sources_are_not_repaired(self):
        for url in ('',None,7,'{avatar_url}','/private/files/photo.jpg','javascript:alert(1)',' '+URL):
            source=page(image(imageSrc=url));self.assertEqual(self.normalize(source),(source,[]))

    def test_multiple_images_and_surrounding_content_keep_original_order_and_paths(self):
        before={'name':'text','fields':{'html':'Before'}};after={'name':'text','fields':{'html':'After'}}
        source=page(before,{'name':'column','children':[image(),image(unknown='keep')]},after)
        # The second unknown field intentionally stays for review.
        out,changes=self.normalize(source)
        self.assertEqual(changes,[{'path':[1,0],'code':labels.CODE}]);self.assertEqual(out['children'][0],before)
        self.assertEqual(out['children'][2],after);self.assertEqual(out['children'][1]['children'][1],source['children'][1]['children'][1])

    def test_idempotence_and_metadata_do_not_contain_source_values(self):
        out,changes=self.normalize(page(image()));self.assertEqual(self.normalize(out),(out,[]))
        self.assertTrue(all(set(x)=={'path','code'} for x in changes));self.assertNotIn('https://',repr(changes))

    def test_account_guard_cannot_apply_mv_rules_to_other_bases(self):
        for field,value in (('ACCOUNT','mv-centr'),('ORIGIN','https://shop.iomp.ru')):
            with patch.object(labels,field,value),self.assertRaisesRegex(Review,'normalization_account_mismatch'):
                self.normalize(page(image()))

    def test_real_core_gate_clears_and_native_image_caption_stays_empty(self):
        source={'account':'mastervision','source_origin':'https://shop.mastervision.su','course_id':1,'lesson_id':4,
                'course_title':'Synthetic','lesson_title':'Synthetic','format':'ape','ape':page(image())}
        images={'photo':'/private/files/photo.jpg'}
        self.assertIn('unsupported_image_settings',_core().plan_import(source,images)['issues'])
        normalized=copy.deepcopy(source);normalized['ape'],_=self.normalize(source['ape'])
        result=_core().plan_import(normalized,images);self.assertTrue(result['ready'],result['issues'])
        self.assertEqual(result['blocks'][0]['data']['url'],images['photo']);self.assertEqual(result['blocks'][0]['data']['caption'],'')

    def test_invalid_tree_and_validator_report_fixed_review(self):
        for source in (None,[],{'name':'text','children':[]},page('bad'),page({'name':'image','fields':[]})):
            with self.assertRaises(Review):self.normalize(source)
        with self.assertRaisesRegex(Review,'image_labels_validator_invalid'):labels.normalize_image_labels(page(),None)


if __name__=='__main__':unittest.main()

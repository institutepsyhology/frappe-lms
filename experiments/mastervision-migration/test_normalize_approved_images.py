"""Owner approvals are tested with synthetic URLs and substituted hash policy."""
import copy
import hashlib
import unittest
from unittest.mock import patch

from importer import Review
import normalize_approved_images as approved
from normalize_editor_nodes import _core

URL='https://f1.autoweboffice.ru/synthetic/missing.jpg'
OTHER='https://f1.autoweboffice.ru/synthetic/other.jpg'
SHA=hashlib.sha256(URL.encode()).hexdigest()


def source():
    return {'name':'page','children':[{'name':'section','children':[
        {'name':'column','children':[{'id':'missing','name':'image','fields':{'anchor':'','imageSrc':URL},'style':{}},
                                    {'name':'text','fields':{'html':'Keep left text'}}]},
        {'name':'column','children':[{'id':'good','name':'image','fields':{'imageSrc':OTHER}},
                                    {'name':'text','fields':{'html':'Keep right text {name}'}}]}]}]}


class ApprovedImageTests(unittest.TestCase):
    def setUp(self):
        self.policy=patch.object(approved,'APPROVED',{(377,3185):SHA,(486,4658):SHA})
        self.policy.start();self.addCleanup(self.policy.stop)

    def test_only_original_target_is_removed_and_all_remaining_nodes_are_exact(self):
        original=source();saved=copy.deepcopy(original);out,changes=approved.normalize_approved_images(original,377,3185)
        expected=copy.deepcopy(original);expected['children'][0]['children'][0]['children'].pop(0)
        self.assertEqual(original,saved);self.assertEqual(out,expected)
        self.assertEqual(changes,[{'path':[0,0,0],'code':approved.CODE,'url_sha256':SHA}])
        self.assertNotIn(URL,str(changes));self.assertNotIn('Keep',str(changes))

    def test_second_exact_binding_is_supported_and_other_courses_or_lessons_are_untouched(self):
        original=source();self.assertEqual(len(approved.normalize_approved_images(original,486,4658)[1]),1)
        for cid,lid in ((377,3186),(486,4659),(297,3185),('377',3185),(377,'3185'),(True,3185)):
            self.assertEqual(approved.normalize_approved_images(original,cid,lid),(original,[]))

    def test_same_image_at_another_path_is_never_removed(self):
        original=source();nodes=original['children'][0]['children'][0]['children'];nodes.reverse()
        self.assertEqual(approved.normalize_approved_images(original,377,3185),(original,[]))
        original=source();original['children'][0]['children'][1]['children'][0]['fields']['imageSrc']=URL
        out,_=approved.normalize_approved_images(original,377,3185)
        self.assertEqual(out['children'][0]['children'][1],original['children'][0]['children'][1])

    def test_changed_hash_whitespace_or_missing_path_leaves_the_complete_tree_unchanged(self):
        for value in (OTHER,' '+URL,URL+' ',None,7):
            original=source();original['children'][0]['children'][0]['children'][0]['fields']['imageSrc']=value
            self.assertEqual(approved.normalize_approved_images(original,377,3185),(original,[]))
        for original in ({'name':'page','children':[]},{'name':'page','children':[{'name':'section','children':[]}]},None):
            self.assertEqual(approved.normalize_approved_images(original,377,3185),(original,[]))

    def test_nonempty_caption_link_anchor_unknown_fields_and_children_are_protected(self):
        cases=[('fields','html','Keep caption'),('fields','caption','Keep caption'),('fields','linkHref','https://example.test/file'),
               ('fields','anchor','bookmark'),('fields','unknown',None),('node','children',[{'name':'text','fields':{'html':'Keep'}}]),
               ('node','callback','open')]
        for where,key,value in cases:
            original=source();node=original['children'][0]['children'][0]['children'][0]
            (node['fields'] if where=='fields' else node)[key]=value
            with self.subTest(field=key):self.assertEqual(approved.normalize_approved_images(original,377,3185),(original,[]))

    def test_inert_optional_fields_are_allowed_but_media_style_or_conditions_are_not(self):
        original=source();node=original['children'][0]['children'][0]['children'][0]
        node['fields'].update({'html':'','linkHref':''});node['children']=[]
        self.assertEqual(len(approved.normalize_approved_images(original,377,3185)[1]),1)
        for style in ({'backgroundImage':{'value':{'url':OTHER}}},{'content':{'value':'Keep material'}},['unknown']):
            original=source();original['children'][0]['children'][0]['children'][0]['style']=style
            self.assertEqual(approved.normalize_approved_images(original,377,3185),(original,[]))
        original=source();original['children'][0]['fields']={'visibleConditions':{'paid':True}}
        self.assertEqual(approved.normalize_approved_images(original,377,3185),(original,[]))

    def test_non_image_node_is_not_a_candidate(self):
        original=source();original['children'][0]['children'][0]['children'][0]['name']='button'
        self.assertEqual(approved.normalize_approved_images(original,377,3185),(original,[]))

    def test_second_pass_is_idempotent_and_never_deletes_the_next_item(self):
        first,_=approved.normalize_approved_images(source(),377,3185)
        self.assertEqual(approved.normalize_approved_images(first,377,3185),(first,[]))

    def test_wrong_source_account_or_origin_is_fatal_before_any_omission(self):
        for field,value in (('ACCOUNT','mv-centr'),('ORIGIN','https://shop.iomp.ru')):
            original=source();before=copy.deepcopy(original)
            with patch.object(approved,field,value),self.assertRaisesRegex(Review,'normalization_account_mismatch'):
                approved.normalize_approved_images(original,377,3185)
            self.assertEqual(original,before)

    def test_actual_core_keeps_other_material_and_needs_no_preparation_of_removed_image(self):
        original={'account':'mastervision','source_origin':'https://shop.mastervision.su','course_id':377,'lesson_id':3185,
                  'course_title':'Synthetic','lesson_title':'Synthetic','format':'ape','ape':source()}
        prepared={'good':'/private/files/good.jpg'}
        self.assertIn('image_not_prepared',_core().plan_import(original,prepared)['issues'])
        normalized=copy.deepcopy(original);normalized['ape'],_=approved.normalize_approved_images(original['ape'],377,3185)
        result=_core().plan_import(normalized,prepared)
        self.assertTrue(result['ready'],result['issues']);self.assertEqual(len(result['blocks']),3)
        self.assertEqual(result['blocks'][1]['data']['url'],'/private/files/good.jpg')


if __name__=='__main__':unittest.main()

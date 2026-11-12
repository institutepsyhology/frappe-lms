"""Synthetic UUID drift and reference safety; no private archives or I/O."""
import copy
import json
import unittest

from canonical_source import canonical_payload, CODE
from importer import Review, Stop

OLD_ROOT='11111111-1111-4111-8111-111111111111'
OLD_CHILD='22222222-2222-4222-8222-222222222222'
NEW_ROOT='33333333-3333-4333-8333-333333333333'
NEW_CHILD='44444444-4444-4444-8444-444444444444'


def payload(root=OLD_ROOT,child=OLD_CHILD):
    return {'account':'mastervision','source_origin':'https://shop.mastervision.su','course_id':3,'lesson_id':3,
            'course_title':'Synthetic course','lesson_title':'Synthetic lesson','format':'ape',
            'ape':{'name':'page','id':root,'children':[{'name':'text','id':child,'fields':{
                'html':'<p>Exact content with {name}</p>','url':'https://example.test/file?p=keep_exact'},
                'style':{'color':{'value':'#123456'}},'children':[]}]}}


class CanonicalTests(unittest.TestCase):
    def test_observed_two_uuid_pattern_reuses_earliest_without_mutation(self):
        old=payload();fresh=payload(NEW_ROOT,NEW_CHILD);old_before=copy.deepcopy(old);before=copy.deepcopy(fresh)
        result,codes=canonical_payload(fresh,[old])
        self.assertEqual(result,old);self.assertEqual(codes,[CODE])
        self.assertEqual(old,old_before);self.assertEqual(fresh,before)
        result['ape']['children'][0]['fields']['html']='modified returned copy'
        self.assertEqual(old,old_before);self.assertEqual(fresh,before)

    def test_exact_duplicate_has_no_warning_and_is_deepcopy(self):
        fresh=payload();result,codes=canonical_payload(fresh,[copy.deepcopy(fresh)])
        self.assertEqual(result,fresh);self.assertEqual(codes,[])
        self.assertIsNot(result,fresh);self.assertIsNot(result['ape'],fresh['ape'])

    def test_history_is_oldest_first_and_earliest_material_equivalent_wins(self):
        first=payload();second=payload('55555555-5555-4555-8555-555555555555','66666666-6666-4666-8666-666666666666')
        fresh=payload(NEW_ROOT,NEW_CHILD)
        self.assertEqual(canonical_payload(fresh,[first,second,fresh]),(first,[CODE]))
        nonmatching=payload();nonmatching['lesson_title']='Different source title'
        self.assertEqual(canonical_payload(fresh,[nonmatching,second]),(second,[CODE]))

    def test_entire_payload_changes_urls_settings_titles_and_node_type_prevent_reuse(self):
        for mutate in [lambda p:p['ape']['children'][0]['fields'].update(url='https://example.test/different'),
                       lambda p:p['ape']['children'][0]['fields'].update(html='<p>Changed content</p>'),
                       lambda p:p['ape']['children'][0]['style']['color'].update(value='#ffffff'),
                       lambda p:p.update(course_title='Changed title'),
                       lambda p:p['ape']['children'][0].update(name='code'),
                       lambda p:p.update(extra_setting={'changed':True})]:
            fresh=payload(NEW_ROOT,NEW_CHILD);mutate(fresh)
            self.assertEqual(canonical_payload(fresh,[payload()]),(fresh,[]))

    def test_json_type_changes_are_not_equal(self):
        for oldvalue,newvalue in [(False,0),(1,1.0),('1',1),([],{}),(None,''),(-0.0,0.0)]:
            old=payload();fresh=payload(NEW_ROOT,NEW_CHILD)
            old['ape']['children'][0]['fields']['setting']=oldvalue
            fresh['ape']['children'][0]['fields']['setting']=newvalue
            self.assertEqual(canonical_payload(fresh,[old]),(fresh,[]))

    def test_children_order_length_and_non_node_id_paths_are_not_ignored(self):
        old=payload();old['ape']['children'].append({'name':'text','id':'77777777-7777-4777-8777-777777777777','fields':{'html':'Different block'}})
        fresh=copy.deepcopy(old);fresh['ape']['id']=NEW_ROOT;fresh['ape']['children'].reverse()
        self.assertEqual(canonical_payload(fresh,[old]),(fresh,[]))
        fresh=payload(NEW_ROOT,NEW_CHILD);fresh['ape']['children'].append({'name':'text','fields':{'html':'Extra'}})
        self.assertEqual(canonical_payload(fresh,[payload()]),(fresh,[]))
        old=payload();fresh=payload(NEW_ROOT,NEW_CHILD)
        old['ape']['children'][0]['fields']['id']=OLD_CHILD;fresh['ape']['children'][0]['fields']['id']=NEW_CHILD
        self.assertEqual(canonical_payload(fresh,[old]),(fresh,[]))

    def test_any_reference_in_values_substrings_keys_anchors_css_or_other_nodes_refuses_reuse(self):
        mutations=[lambda p:p['ape']['children'][0]['fields'].update(anchor=OLD_CHILD),
                   lambda p:p['ape']['children'][0]['fields'].update(html='<div id="'+OLD_CHILD+'">Keep</div>'),
                   lambda p:p['ape']['children'][0]['fields'].update(url='https://example.test/?ref='+OLD_ROOT),
                   lambda p:p['ape']['children'][0]['style'].update(selector='#'+OLD_CHILD+' .caption'),
                   lambda p:p.update(metadata={OLD_ROOT:{'keep':True}}),
                   lambda p:p.update(metadata={'prefix-'+NEW_CHILD+'-suffix':'keep'}),
                   lambda p:p.update(metadata={'data':{'refs':[OLD_ROOT]}}),
                   lambda p:p['ape']['children'].append({'name':'text','id':'prefix-'+OLD_CHILD,'fields':{'html':'Keep'}})]
        for mutate in mutations:
            old=payload();fresh=payload(NEW_ROOT,NEW_CHILD);mutate(old);mutate(fresh)
            self.assertEqual(canonical_payload(fresh,[old]),(fresh,[]))

    def test_duplicate_ids_cross_node_swaps_nonuuid_and_id_type_changes_refuse_reuse(self):
        for old,fresh in [(payload(OLD_ROOT,OLD_ROOT),payload(NEW_ROOT,NEW_ROOT)),
                          (payload(),payload(OLD_CHILD,OLD_ROOT)),
                          (payload('old-root','old-child'),payload('new-root','new-child')),
                          (payload(),payload(NEW_ROOT,42))]:
            self.assertEqual(canonical_payload(fresh,[old]),(fresh,[]))

    def test_unrelated_dict_id_even_uuid_is_real_content(self):
        old=payload();fresh=payload(NEW_ROOT,NEW_CHILD)
        old['metadata']={'name':'text','id':OLD_ROOT,'children':[]}
        fresh['metadata']={'name':'text','id':NEW_ROOT,'children':[]}
        self.assertEqual(canonical_payload(fresh,[old]),(fresh,[]))
        old=payload();fresh=payload(NEW_ROOT,NEW_CHILD)
        old['format']=fresh['format']='preview'
        self.assertEqual(canonical_payload(fresh,[old]),(fresh,[]))

    def test_foreign_current_or_history_identity_is_fatal_even_after_matching_history(self):
        current=payload(NEW_ROOT,NEW_CHILD)
        for field,value in [('account','mv-centr'),('source_origin','https://shop.mv-centr.ru'),
                            ('course_id',4),('lesson_id',4),('course_id','3')]:
            bad=payload();bad[field]=value
            with self.assertRaises(Stop):canonical_payload(current,[payload(),bad])
        for field,value in [('account','iomp'),('source_origin','https://shop.iomp.ru'),('course_id',False)]:
            bad=payload();bad[field]=value
            with self.assertRaises(Stop):canonical_payload(bad,[])

    def test_empty_history_real_changed_history_and_uuid_case_preserve_exact_values(self):
        current=payload(NEW_ROOT,NEW_CHILD)
        self.assertEqual(canonical_payload(current,[]),(current,[]))
        changed=payload();changed['ape']['children'][0]['fields']['html']='Old real content'
        self.assertEqual(canonical_payload(current,[changed]),(current,[]))
        old=payload('aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa','bbbbbbbbbbbb4bbb8bbbbbbbbbbbbbbb')
        self.assertEqual(canonical_payload(current,[old]),(old,[CODE]))

    def test_invalid_history_container_or_non_json_values_fail_fixed_review(self):
        with self.assertRaisesRegex(Review,'canonical_source_invalid'):canonical_payload(payload(),None)
        bad=payload();bad['extra']=float('nan')
        with self.assertRaisesRegex(Review,'canonical_source_invalid'):canonical_payload(bad,[])


if __name__=='__main__':unittest.main()

"""Scoped image/self-link conversion; synthetic inputs, no Frappe or network."""
import copy
import hashlib
from html.parser import HTMLParser
import json
import unittest
from unittest.mock import patch

from lms.lms import avo_transform as mod

SOURCE = 'https://f1.autoweboffice.com/synthetic/worksheet.png'
ACTUAL = '/private/files/existing-renamed-image-17.png'
SCOPES = (('mastervision','636','7363'),('mastervision','640','7415'))
STYLE = {'lists':{}}


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def style_digest(value):
    return digest(json.dumps(value,ensure_ascii=True,sort_keys=True,separators=(',',':'),allow_nan=False))


def payload(scope=SCOPES[0]):
    return {'account':scope[0],'source_origin':'https://shop.mastervision.su',
            'course_id':scope[1],'lesson_id':scope[2],
            'course_title':'Synthetic course','lesson_title':'Synthetic lesson','format':'ape',
            'ape':{'name':'page','children':[{'name':'image','id':'picture','style':copy.deepcopy(STYLE),
                'fields':{'anchor':'','html':'Изображение','imageSrc':SOURCE,
                          'linkHref':SOURCE,'linkTarget':True}}]}}


class Link(HTMLParser):
    def __init__(self):super().__init__();self.tags=[];self.text=[]
    def handle_starttag(self,tag,attrs):self.tags.append((tag,dict(attrs)))
    def handle_data(self,data):self.text.append(data)


class SelfLinkedImagesTests(unittest.TestCase):
    def plan(self,source=None,urls=None):
        rules={scope:(digest(SOURCE),style_digest(STYLE)) for scope in SCOPES}
        with patch.dict(mod.REVIEWED_SELF_LINKED_IMAGES,rules,clear=True):
            return mod.plan_import(payload() if source is None else source,
                                   {'picture':ACTUAL} if urls is None else urls)

    def test_only_the_two_confirmed_source_identities_are_configured(self):
        self.assertEqual(set(mod.REVIEWED_SELF_LINKED_IMAGES),set(SCOPES))
        for image_hash,layout_hash in mod.REVIEWED_SELF_LINKED_IMAGES.values():
            self.assertEqual(image_hash,'f7ca50c355f1de74132ff4f072bed77ae52d7ad2a0bd9500726abc9c8afa757e')
            self.assertEqual(layout_hash,'bc41cd4c18cb722ce66eaa375ed43d71f1a9aa3e1990df7684782096934c3858')

    def test_image_and_new_tab_link_use_the_exact_actual_prepared_file(self):
        for scope in SCOPES:
            source=payload(scope);before=copy.deepcopy(source);plan=self.plan(source)
            self.assertTrue(plan['ready'],plan['issues']);self.assertEqual(source,before)
            self.assertEqual([b['type'] for b in plan['blocks']],['image','paragraph'])
            self.assertEqual(plan['blocks'][0]['data'],{'url':ACTUAL,'caption':'',
                'withBorder':False,'withBackground':False,'stretched':False})
            parser=Link();parser.feed(plan['blocks'][1]['data']['text'])
            self.assertEqual(parser.tags,[('a',{'href':ACTUAL,'target':'_blank','rel':'noopener noreferrer'})])
            self.assertEqual(''.join(parser.text),'Открыть изображение')
            self.assertNotIn('autoweboffice',json.dumps(plan['blocks']))
            self.assertIn('image_self_link_preserved',plan['warnings'])

    def test_file_deduplication_or_rename_is_not_predicted_from_source_hash(self):
        for actual in ('/private/files/deduplicated-existing.jpg','/private/files/another-file.webp'):
            plan=self.plan(urls={'picture':actual})
            self.assertTrue(plan['ready']);self.assertEqual(plan['blocks'][0]['data']['url'],actual)
            self.assertIn('href="'+actual+'"',plan['blocks'][1]['data']['text'])

    def test_missing_public_external_or_unsafe_prepared_file_never_creates_link(self):
        for actual in (None,'/files/public.png','https://example.test/private/files/foreign.png',
                       '/private/files/../other.png','/private/files/a..png',
                       '/private/files/picture.png?token=private','/private/files/picture.png#fragment',
                       '/private/files/x"onclick="bad.png','/private/files/sub/picture.png'):
            with self.subTest(actual=actual):
                plan=self.plan(urls={} if actual is None else {'picture':actual})
                self.assertFalse(plan['ready']);self.assertIn('image_not_prepared',plan['issues'])
                self.assertFalse(any(b['type']=='paragraph' for b in plan['blocks']))

    def test_changed_source_link_label_target_anchor_or_fields_require_review(self):
        for key,value in (('imageSrc',SOURCE+'?new=1'),('linkHref','https://example.test/different.png'),
                          ('html','Visible real caption'),('linkTarget',False),('linkTarget',1),
                          ('linkTarget','true'),('anchor','meaningful'),('unknown','material'),
                          ('visibleConditions',{'protected':True})):
            source=payload();source['ape']['children'][0]['fields'][key]=value
            with self.subTest(key=key,value=value):
                plan=self.plan(source);self.assertFalse(plan['ready'])
                self.assertIn('unsupported_image_settings',plan['issues'])

    def test_children_extra_node_data_and_changed_layout_are_not_discarded(self):
        for key,value in (('children',[{'name':'text','fields':{'html':'Keep child'}}]),
                          ('extra',None),('style',{'content':'Keep material'})):
            source=payload();source['ape']['children'][0][key]=value
            before=copy.deepcopy(source);plan=self.plan(source)
            self.assertFalse(plan['ready']);self.assertEqual(source,before)
            self.assertIn('unsupported_image_settings',plan['issues'])

    def test_account_course_lesson_and_origin_are_strictly_scoped(self):
        for key,value in (('account','mv-centr'),('course_id','637'),('lesson_id','7364'),
                          ('source_origin','https://shop.mv-centr.ru'),('source_origin',None)):
            source=payload();source[key]=value
            with self.subTest(key=key):
                plan=self.plan(source);self.assertFalse(plan['ready'])
                self.assertIn('unsupported_image_settings',plan['issues'])

    def test_unlinked_native_image_output_stays_exact_and_general_urls_stay_strict(self):
        source=payload();source['ape']['children'][0]['fields']={'anchor':'','imageSrc':SOURCE}
        plan=self.plan(source)
        self.assertTrue(plan['ready'],plan['issues'])
        self.assertEqual(plan['blocks'],[{'type':'image','data':{'url':ACTUAL,'caption':'',
            'withBorder':False,'withBackground':False,'stretched':False}}])
        self.assertNotIn('image_self_link_preserved',plan['warnings'])
        self.assertFalse(mod._url(ACTUAL))
        self.assertFalse(mod._safe_html('<a href="'+ACTUAL+'">Image</a>'))

    def test_preview_input_cannot_request_internal_self_link_flag(self):
        source=payload();source.pop('ape');source['format']='preview'
        source['content']=[{'type':'image','image_key':'picture','self_link':True}]
        plan=self.plan(source)
        self.assertFalse(plan['ready']);self.assertFalse(any(b['type']=='paragraph' for b in plan['blocks']))

    def test_sequence_and_repeated_pure_plans_are_stable(self):
        source=payload();source['ape']['children'].insert(0,{'name':'text','fields':{'html':'Before'}})
        source['ape']['children'].append({'name':'text','fields':{'html':'After'}})
        first=self.plan(source);second=self.plan(source)
        self.assertEqual(first,second);self.assertTrue(first['ready'])
        self.assertEqual([b['type'] for b in first['blocks']],['paragraph','image','paragraph','paragraph'])
        self.assertEqual(first['blocks'][0]['data']['text'],'Before')
        self.assertEqual(first['blocks'][-1]['data']['text'],'After')


if __name__=='__main__':unittest.main()

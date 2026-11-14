import copy
from html.parser import HTMLParser
import unittest
from unittest.mock import patch

from importer import Review
from normalize_editor_nodes import _core
from normalize_source import static_validator
import normalize_reviewed_shared_image as subject


SOURCE = 'https://f1.autoweboffice.com/synthetic/worksheet.jpg'


def page():
    before=[{'name':'text','fields':{'html':'Before '+str(i)}}for i in range(4)]
    image={'id':'picture','name':'image','style':{},'fields':{'anchor':'','html':'Изображение',
           'imageSrc':SOURCE,'linkHref':SOURCE,'linkTarget':True}}
    return {'name':'page','children':before+[image,{'name':'text','fields':{'html':'After'}}]}


def bind(ape):
    node=ape['children'][4]
    return patch.object(subject,'BINDINGS',{(634,7364):{'path':(4,),
        'ape_sha256':subject._digest(ape),'node_sha256':subject._digest(node),
        'style_sha256':subject._digest(node.get('style'),ascii=True),
        'source_url_sha256':subject._sha(SOURCE)}})


def normalize(ape,context=(634,7364)):
    return subject.normalize_reviewed_shared_image(ape,*context,static_validator())


class Links(HTMLParser):
    def __init__(self):super().__init__();self.hrefs=[]
    def handle_starttag(self,t,a):
        if t=='a':self.hrefs.append(dict(a).get('href'))


class SharedImageTests(unittest.TestCase):
    def test_plain_image_plus_explicit_local_button_preserves_all_neighbours_and_source(self):
        ape=page();before=copy.deepcopy(ape)
        with bind(ape):
            result,receipts=normalize(ape)
            self.assertEqual(normalize(ape),(result,receipts))
        self.assertEqual(ape,before)
        self.assertEqual(result['children'][:4],ape['children'][:4])
        self.assertEqual(result['children'][6:],ape['children'][5:])
        self.assertEqual(result['children'][4]['fields'],{'anchor':'','imageSrc':SOURCE})
        self.assertEqual(result['children'][4]['style'],ape['children'][4]['style'])
        button=result['children'][5]
        self.assertEqual(button['name'],'button');self.assertIs(button['fields']['blank'],True)
        self.assertEqual(button['fields']['html'],'Изображение')
        payload={'account':'mastervision','source_origin':'https://shop.mastervision.su',
                 'course_id':634,'lesson_id':7364,'course_title':'Synthetic','lesson_title':'Synthetic',
                 'format':'ape','ape':result}
        plan=_core().plan_import(payload,image_urls={'picture':subject.PINNED_TARGET_PATH})
        self.assertTrue(plan['ready'],plan['issues'])
        images=[b for b in plan['blocks']if b['type']=='image']
        self.assertEqual(images[0]['data']['url'],subject.PINNED_TARGET_PATH)
        links=Links()
        for b in plan['blocks']:
            if b['type']=='paragraph':links.feed(b['data']['text'])
        self.assertIn('https://'+subject.SITE+subject.PINNED_TARGET_PATH,links.hrefs)
        self.assertTrue(receipts[0]['requires_post_import_same_url_verification'])
        self.assertEqual(receipts[0]['image_md5'],subject.IMAGE_MD5)

    def test_identity_changes_are_never_aliased_to_an_approved_lesson(self):
        ape=page()
        with bind(ape):
            for scope in ((634,7363),(636,7364),(640,7415)):
                self.assertEqual(normalize(ape,scope),(ape,[]))
        with patch.object(subject,'ACCOUNT','mv-centr'):
            with self.assertRaisesRegex(Review,'account_mismatch'):normalize(ape)

    def test_any_raw_root_node_or_layout_edit_fails_the_four_hash_guards(self):
        ape=page()
        with bind(ape):
            for key in ('root','node','style','link'):
                changed=copy.deepcopy(ape)
                if key=='root':changed['fields']={'extra':'Keep'}
                if key=='node':changed['children'][4]['id']='changed'
                if key=='style':changed['children'][4]['style']['caption']='Keep'
                if key=='link':changed['children'][4]['fields']['linkHref']='https://example.test/other'
                with self.subTest(key=key),self.assertRaisesRegex(Review,'source_changed'):normalize(changed)

    def test_unknown_fields_children_conditions_labels_and_targets_are_not_dropped(self):
        for key,value in (('anchor','Keep'),('html','Real caption'),('linkTarget',False),
                          ('linkTarget',1),('visibleConditions',{'paid':1}),('future','Keep')):
            ape=page();ape['children'][4]['fields'][key]=value
            with self.subTest(key=key,value=value),bind(ape),self.assertRaises(Review):normalize(ape)
        ape=page();ape['children'][4]['children']=[{'name':'text','fields':{'html':'Keep'}}]
        with bind(ape),self.assertRaises(Review):normalize(ape)

    def test_unverified_or_unsafe_pinned_paths_cannot_become_links(self):
        for path in ('/files/public.jpg','/private/files/other.jpg','/private/files/../x.jpg',
                     '/private/files/x.jpg?token=1','https://example.test/private/files/x.jpg'):
            ape=page()
            with bind(ape),patch.object(subject,'PINNED_TARGET_PATH',path),self.assertRaises(Review):normalize(ape)

    def test_public_bindings_are_exact_and_reference_metadata_is_consistent(self):
        self.assertEqual(set(subject.BINDINGS),{(634,7364)})
        self.assertEqual(subject._sha(subject.PINNED_TARGET_PATH),subject.PINNED_TARGET_PATH_SHA256)
        self.assertTrue(subject.PINNED_TARGET_PATH.endswith('avo-'+subject.IMAGE_SHA256+'.jpg'))
        self.assertEqual(subject.IMAGE_SIZE,221327)
        self.assertEqual(subject.FILE_OWNER,'Administrator')
        self.assertNotIn('https://',repr(subject.BINDINGS))


if __name__=='__main__':unittest.main()

import copy
import hashlib
import unittest
from unittest.mock import patch

import normalize_reviewed_email_html as subject
from importer import Review
from normalize_source import static_validator, normalize_payload
from normalize_editor_nodes import _core


BG = 'https://assets.example.test/paper.jpg'
BODY = 'http://f1.autoweboffice.ru/files/synthetic/avatar.png'
LINK = 'https://example.org/material.pdf'
AUX = '<meta charset="utf-8"><title></title><style type="text/css">p {font-family:Arial,sans-serif;font-size:16px;color:#303030}</style><script type="text/javascript">var lang="ru";</script>'


def sha(value): return hashlib.sha256(value.encode()).hexdigest()


def email(body=None):
    content = body if body is not None else ('<p><strong>Keep heading</strong></p><p>Keep &amp; text</p>'
        '<p><a href="' + LINK + '" style="color:#ffffff;background:#cc3333;border-style:solid;border-color:#cc3333;border-width:6px 20px;border-radius:4px;display:inline-block;min-width:125px;height:auto;word-break:break-word">Keep file</a></p>'
        '<p><img alt="" src="' + BODY + '" style="width:100px;height:100px"></p><p>Keep final</p>')
    for depth in range(4):
        style = (' style="background-image:url(\''+BG+'\');padding:50px 45px 40px;min-width:600px;width:600px"' if depth == 0 else '')
        content = '<table width="600"'+style+'><tbody><tr><td align="center">'+content+'</td></tr></tbody></table>'
    return AUX + '<div id="fb-root" style="display:none"></div>' + content


def page(html):
    return {'name':'page','fields':{},'children':[
        {'name':'text','id':'original-node','fields':{'html':html,'anchor':''},'style':{}},
        {'name':'text','fields':{'html':'<p>Sibling</p>'}}]}


class ReviewedEmailTests(unittest.TestCase):
    def apply(self, html, ape=None):
        source = page(html) if ape is None else ape
        aux = subject._Document(html).auxiliary_hashes()
        receipts = {
            'background':{'original_url_sha256':sha(BG),'transport_url_sha256':sha(BG),'content_sha256':'a'*64,'size':100},
            'body_image':{'original_url_sha256':sha(BODY),'transport_url_sha256':sha(BODY.replace('http:','https:',1)),'content_sha256':'b'*64,'size':200}}
        with patch.object(subject,'APPROVED',{(105,1539):((0,),sha(html))}), patch.object(subject,'KNOWN_AUXILIARY',set(aux)), patch.object(subject,'ASSETS',receipts):
            return subject.normalize_reviewed_email_html(source,105,1539,static_validator())

    def test_preserves_all_text_links_body_image_and_background(self):
        html=email();source=page(html);saved=copy.deepcopy(source)
        result,changes=self.apply(html,source)
        self.assertEqual(source,saved);self.assertEqual(result['children'][1],source['children'][1])
        group=result['children'][0]
        self.assertEqual(group['id'],'original-node');self.assertEqual(group['name'],'section')
        self.assertEqual(group['children'][0]['fields']['imageSrc'],BG)
        markup=group['children'][1]['fields']['html']
        self.assertNotIn('<table',markup);self.assertNotIn('<script',markup);self.assertNotIn('<style',markup)
        self.assertIn(BODY.replace('http:','https:',1),markup);self.assertIn(LINK,markup)
        self.assertIn('Keep &amp; text',markup);self.assertIn('Keep final',markup)
        self.assertIn(subject.LAYOUT_CODE,[c['code'] for c in changes])
        with patch.object(subject,'ASSETS',{'body_image':{'original_url_sha256':sha(BODY),'transport_url_sha256':sha(BODY.replace('http:','https:',1))}}):
            self.assertEqual(subject._material(html),subject._material(markup,upgraded=True))

    def test_portable_styles_and_readable_colored_button_are_preserved(self):
        result,_=self.apply(email());markup=result['children'][0]['children'][1]['fields']['html']
        self.assertIn('background:#cc3333',markup);self.assertIn('color:#ffffff',markup)
        self.assertIn('border-top:6px solid #cc3333',markup);self.assertIn('overflow-wrap:break-word',markup)
        self.assertIn('font-size:16px',markup);self.assertIn('color:#303030',markup)

    def test_full_pipeline_keeps_two_images_and_all_materials(self):
        result,_=self.apply(email());payload={'account':'mastervision','source_origin':'https://shop.mastervision.su','course_id':105,'lesson_id':1539,'course_title':'Synthetic course','lesson_title':'Synthetic lesson','format':'ape','ape':result}
        prepared,_=normalize_payload(payload);images={};pending=[prepared['ape']]
        while pending:
            node=pending.pop();pending.extend(node.get('children',[]))
            if node['name']=='image':images[node['id']]='/private/files/synthetic.png'
        plan=_core().plan_import(prepared,image_urls=images)
        self.assertTrue(plan['ready'],plan['issues']);self.assertEqual(sum(b['type']=='image' for b in plan['blocks']),2)

    def test_only_exact_source_hash_path_identity_and_kind_are_repaired(self):
        html=email();source=page(html)
        with patch.object(subject,'APPROVED',{(105,1539):((0,),'0'*64)}):
            self.assertEqual(subject.normalize_reviewed_email_html(source,105,1539,static_validator()),(source,[]))
        for cid,lid in ((True,1539),('0105',1539),(106,1539),(105,1540)):
            self.assertEqual(subject.normalize_reviewed_email_html(source,cid,lid,static_validator()),(source,[]))
        source['children'][0]['name']='header';self.assertEqual(self.apply(html,source),(source,[]))

    def test_anchors_conditions_unknown_fields_and_style_material_stay_for_review(self):
        html=email()
        for target,key,value in (('node','anchor','important'),('node','visibleConditions',{}),('root','displayDelay',0)):
            source=page(html);node=source if target=='root' else source['children'][0];node['fields'][key]=value
            self.assertEqual(self.apply(html,source),(source,[]))
        source=page(html);source['children'][0]['style']={'caption':'Keep'}
        self.assertEqual(self.apply(html,source),(source,[]))

    def test_data_tables_hidden_text_and_unknown_material_are_never_dropped(self):
        for html in (email().replace('<td align="center">','<td>Extra cell</td><td align="center">',1),
                     email().replace('<div id="fb-root" style="display:none"></div>','<div id="fb-root" style="display:none">Keep hidden</div>'),
                     email().replace('<p>Keep final</p>','<form>Keep response</form>'),
                     email().replace('<title></title>','<title>Authored heading</title>')):
            with self.subTest(html=sha(html)),self.assertRaises(Review):self.apply(html)

    def test_unknown_script_or_stylesheet_is_not_silently_discarded(self):
        html=email();known=set(subject._Document(html).auxiliary_hashes())
        for changed in (html.replace('var lang="ru";','document.write("Keep authored");'),html.replace('p {font-family','p::before {content:"Keep"} p {font-family')):
            with patch.object(subject,'APPROVED',{(105,1539):((0,),sha(changed))}),patch.object(subject,'KNOWN_AUXILIARY',known),self.assertRaises(Review):
                subject.normalize_reviewed_email_html(page(changed),105,1539,static_validator())

    def test_changed_background_or_body_url_requires_review(self):
        for html in (email().replace(BG,BG+'?changed=1'),email().replace(BODY,BODY+'?changed=1')):
            with self.assertRaises(Review):self.apply(html)

    def test_known_comment_is_traced_and_unknown_comment_is_refused(self):
        comment='<!--[if mso]><xml>Office settings</xml><![endif]-->'
        with patch.object(subject,'KNOWN_COMMENTS',{sha(comment)}):
            result,changes=self.apply(comment+email())
        self.assertTrue(any(r['tag']=='comment' and r['source_sha256']==sha(comment) for r in changes[0]['auxiliary_elements']))
        with self.assertRaises(Review):self.apply(comment+email())

    def test_material_mismatch_fails_with_fatal_diagnostic(self):
        with patch.object(subject,'_material',side_effect=[('before',[],[]),('after',[],[])]):
            with self.assertRaisesRegex(Review,'^reviewed_email_material_mismatch$'):self.apply(email())

    def test_bad_tree_and_account_fail_with_fixed_codes(self):
        html=email();source=page(html);source['children'][1]['children']=None
        with self.assertRaisesRegex(Review,'^reviewed_email_source_invalid$'):self.apply(html,source)
        with patch.object(subject,'ACCOUNT','mv-centr'),self.assertRaisesRegex(Review,'^reviewed_email_account_mismatch$'):
            subject.normalize_reviewed_email_html(page(html),105,1539,static_validator())

    def test_white_link_without_opaque_colored_background_is_refused(self):
        with self.assertRaises(Review):self.apply(email().replace('background:#cc3333;',''))

    def test_second_application_and_original_input_are_stable(self):
        html=email();result,_=self.apply(html)
        self.assertEqual(self.apply(html,result),(result,[]))


if __name__=='__main__':unittest.main()

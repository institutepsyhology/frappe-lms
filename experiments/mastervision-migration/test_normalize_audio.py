"""Synthetic audio receipts and pure converter checks; no files or network."""
import copy
import hashlib
import json
import unittest
from unittest.mock import patch

from importer import Review
import normalize_audio as mod
from normalize_editor_nodes import _core

SOURCE = 'https://f1.autoweboffice.ru/files/100/synthetic-audio.mp3'
SECOND = 'https://f1.autoweboffice.com/files/100/second-audio.mp3'
SHA = 'a' * 64


def key(url=SOURCE): return hashlib.sha256(url.encode()).hexdigest()
def receipt(**values):
    return {'file_url':'/private/files/avo-mastervision-audio-'+SHA+'.mp3','sha256':SHA,
            'md5':'b'*32,'size':40558987,**values}
def audio(url=SOURCE, **fields):
    return {'id':'audio-uuid','name':'audio','fields':{'anchor':'','audioSrc':url,
        'showDownloadButton':True,'showLoopButton':False,'showStopButton':True,
        'showVolumeButton':False,'showVolumeSlider':True,**fields},'children':[],
        'style':{'spacing':{'margin':'8px'}}}
def text(value): return {'name':'text','fields':{'html':value}}
def page(*children): return {'name':'page','children':list(children)}


class AudioTests(unittest.TestCase):
    def test_conversion_preserves_source_order_id_and_style_without_mutation(self):
        source=page(text('Before'),audio(),text('After'));before=copy.deepcopy(source)
        assets={key():receipt()};assets_before=copy.deepcopy(assets)
        out,changes=mod.normalize_audio(source,assets)
        self.assertEqual(source,before);self.assertEqual(assets,assets_before)
        self.assertEqual(out['children'][::2],source['children'][::2])
        node=out['children'][1]
        self.assertEqual(node['name'],'button');self.assertEqual(node['id'],'audio-uuid')
        self.assertEqual(node['style'],source['children'][1]['style'])
        self.assertEqual(node['children'],[])
        self.assertEqual(node['fields'],{'anchor':'','html':'Аудиозапись','linkType':'url',
            'url':'https://my-lk.mastervision.su'+receipt()['file_url'],'blank':True})
        self.assertEqual(changes,[{'path':[1],'code':mod.CODE,'url_sha256':key()}])
        self.assertNotIn('autoweboffice',json.dumps(out))

    def test_multiple_and_nested_audio_uses_exact_map_keys_and_preserves_order(self):
        source=page({'name':'column','children':[audio(),text('Middle'),audio(SECOND)]},audio())
        out,changes=mod.normalize_audio(source,{key():receipt(),key(SECOND):receipt()})
        self.assertEqual([row['path'] for row in changes],[[0,0],[0,2],[1]])
        self.assertEqual([row['url_sha256'] for row in changes],[key(),key(SECOND),key()])
        self.assertEqual(out['children'][0]['children'][1],text('Middle'))

    def test_core_renders_an_ordinary_paragraph_anchor_to_private_file(self):
        ape,_=mod.normalize_audio(page(audio()),{key():receipt()})
        payload={'account':'mastervision','source_origin':'https://shop.mastervision.su',
            'course_id':123,'lesson_id':456,'course_title':'Synthetic course',
            'lesson_title':'Synthetic lesson','format':'ape','ape':ape}
        plan=_core().plan_import(payload)
        self.assertTrue(plan['ready'],plan['issues'])
        body=plan['blocks']
        self.assertEqual(body[0]['type'],'paragraph')
        self.assertIn('https://my-lk.mastervision.su/private/files/',body[0]['data']['text'])
        self.assertNotIn('autoweboffice',json.dumps(body))

    def test_no_audio_and_no_map_is_a_pure_unchanged_copy(self):
        source=page(text('Only text'));out,changes=mod.normalize_audio(source,None)
        self.assertEqual(out,source);self.assertIsNot(out,source);self.assertEqual(changes,[])

    def test_normalized_button_is_idempotent_without_a_map(self):
        first,_=mod.normalize_audio(page(audio()),{key():receipt()})
        second,changes=mod.normalize_audio(first,None)
        self.assertEqual(second,first);self.assertEqual(changes,[])

    def test_missing_mapping_requires_preparation_only_for_recognized_audio(self):
        for assets in (None,{}, {'c'*64:receipt()}):
            with self.subTest(assets=assets),self.assertRaisesRegex(Review,'^audio_asset_not_prepared$'):
                mod.normalize_audio(page(audio()),assets)

    def test_wrong_account_site_or_origin_is_rejected_before_mapping(self):
        for field,value in (('ACCOUNT','mv-centr'),('ORIGIN','https://shop.iomp.ru'),('SITE','my-lk.mv-centr.ru')):
            with patch.object(mod,field,value),self.assertRaisesRegex(Review,'^audio_account_mismatch$'):
                mod.normalize_audio(page(audio()),None)

    def test_source_urls_are_strict_and_never_unescaped_or_rewritten(self):
        bad=('http://f1.autoweboffice.ru/file.mp3','https://shop.mv-centr.ru/file.mp3',
             'https://f1.autoweboffice.ru:443/file.mp3','https://user@f1.autoweboffice.ru/file.mp3',
             SOURCE+'?download=1',SOURCE+'#fragment','https://f1.autoweboffice.ru/files/../file.mp3',
             'https://f1.autoweboffice.ru/files/%2fprivate.mp3','https://f1.autoweboffice.ru/files/%250a.mp3',
             'https://f1.autoweboffice.ru/files/%0a.mp3','https://f1.autoweboffice.ru/files/bad%XX.mp3',
             'https://f1.autoweboffice.ru/files/image.png',SOURCE+'\n')
        for url in bad:
            with self.subTest(url=url),self.assertRaisesRegex(Review,'^audio_source_url_invalid$'):
                mod.normalize_audio(page(audio(url)),None)

    def test_valid_utf8_encoded_source_uses_the_exact_original_url_hash(self):
        url='https://f1.autoweboffice.ru/files/100/%D0%90%D1%83%D0%B4%D0%B8%D0%BE.mp3'
        out,changes=mod.normalize_audio(page(audio(url)),{key(url):receipt()})
        self.assertEqual(changes[0]['url_sha256'],key(url))
        self.assertEqual(out['children'][0]['name'],'button')

    def test_asset_path_host_hash_type_and_receipt_fields_must_match(self):
        bad=[receipt(file_url='/files/avo-mastervision-audio-'+SHA+'.mp3'),
             receipt(file_url='https://my-lk.mastervision.su'+receipt()['file_url']),
             receipt(file_url='https://my-lk.iomp.ru'+receipt()['file_url']),
             receipt(file_url='/private/files/avo-mastervision-audio-'+'c'*64+'.mp3'),
             receipt(file_url=receipt()['file_url']+'?x=1'),receipt(sha256='A'*64),
             receipt(md5='bad'),receipt(size=True),receipt(size=0),receipt(size=2**53),
             receipt(size='10'),receipt(account='mv-centr'),{'file_url':receipt()['file_url']}]
        for item in bad:
            with self.subTest(item=item),self.assertRaisesRegex(Review,'^audio_asset_mapping_invalid$'):
                mod.normalize_audio(page(audio()),{key():item})
        with self.assertRaisesRegex(Review,'^audio_asset_mapping_invalid$'):
            mod.normalize_audio(page(audio()),[])

    def test_unknown_fields_controls_anchors_children_and_content_styles_stay_for_review(self):
        nodes=[audio(mystery='material'),audio(anchor='important'),audio(showLoopButton='yes'),
               audio(visibleConditions={'goodsIds':[1]}),audio()]
        nodes[-1]['children']=[text('Caption')]
        for style in ({'background':'url(https://example.test/photo.png)'},{'display':'none'},{'opacity':0},{'caption':'Real caption'}):
            node=audio();node['style']=style;nodes.append(node)
        node=audio();node['extra']='material';nodes.append(node)
        for node in nodes:
            source=page(node)
            with self.subTest(node=node):
                out,changes=mod.normalize_audio(source,None)
                self.assertEqual(out,source);self.assertEqual(changes,[])

    def test_conditional_ancestor_prevents_unconditional_audio_conversion(self):
        source=page({'name':'column','fields':{'visibleConditions':{'conditions':[1]}},'children':[audio()]})
        out,changes=mod.normalize_audio(source,None)
        self.assertEqual(out,source);self.assertEqual(changes,[])

    def test_observed_full_opacity_editor_control_is_preserved_exactly(self):
        node=audio();node['style']={'lists':{'player':{'opacity':{'value':{'number':1}}}}}
        source=page(node);out,changes=mod.normalize_audio(source,{key():receipt()})
        self.assertEqual(len(changes),1)
        self.assertEqual(out['children'][0]['style'],node['style'])
        self.assertEqual(source['children'][0],node)
        for value in (0,True,'1',0.5):
            node=audio();node['style']={'lists':{'player':{'opacity':{'value':{'number':value}}}}}
            source=page(node);out,changes=mod.normalize_audio(source,None)
            self.assertEqual(out,source);self.assertEqual(changes,[])
        node=audio();node['style']={'other':{'opacity':{'value':{'number':1}}}}
        self.assertEqual(mod.normalize_audio(page(node),None),(page(node),[]))

    def test_malformed_tree_and_audio_source_types_fail_with_fixed_codes(self):
        for source in (None,{},page({'name':'audio','fields':[]})):
            with self.assertRaisesRegex(Review,'^audio_nodes_invalid$'):mod.normalize_audio(source,None)
        for source in (None,12,False,[]):
            with self.assertRaisesRegex(Review,'^audio_source_url_invalid$'):
                mod.normalize_audio(page(audio(source)),None)

    def test_visible_desktop_and_mobile_controls_preserve_audio_and_style(self):
        lists = {}
        for prefix in ('', '$__max_width__576__', '$__max_width__768__'):
            lists[prefix + 'block'] = {'display': {'value': {'visible': 'block'}}}
            lists[prefix + 'player'] = {'opacity': {'value': {'number': 1}}}
        node = audio(); node['style'] = {'lists': lists}; source = page(node)
        out, changes = mod.normalize_audio(source, {key(): receipt()})
        self.assertEqual(len(changes), 1)
        self.assertEqual(out['children'][0]['style'], node['style'])
        self.assertEqual(source, page(node))
        for bad in ({'value': {'visible': 'none'}}, {'value': {'visible': False}},
                    {'value': {'visible': 'block', 'condition': 'private'}}):
            changed = copy.deepcopy(source)
            changed['children'][0]['style']['lists']['$__max_width__576__block']['display'] = bad
            self.assertEqual(mod.normalize_audio(changed, None), (changed, []))
        for group in ('other', '$__max_width__999__block'):
            changed = copy.deepcopy(source)
            changed['children'][0]['style']['lists'][group] = {'display': {'value': {'visible': 'block'}}}
            self.assertEqual(mod.normalize_audio(changed, None), (changed, []))


if __name__=='__main__':unittest.main()

import copy
import hashlib
from html.parser import HTMLParser
import json
import unittest
from unittest.mock import patch

from importer import Review
from normalize_editor_nodes import _core
from normalize_source import static_validator
import normalize_reviewed_keycap_lesson as subject


FRAME = ('<iframe src="https://www.youtube.com/embed/abcdefghijk?rel=0" width="560" height="315" '
         'allow="autoplay; encrypted-media; picture-in-picture" frameborder="0" allowfullscreen></iframe>')
IMG_STYLE = 'box-sizing: border-box; border: 0px; vertical-align: middle;'
MARK_STYLE = ('box-sizing: border-box; background: rgb(255, 214, 30); padding: 0.2rem 0.4rem; '
              'display: inline-block; line-height: 1; border-radius: 4px;')


def image(number):
    return '<img src="https://'+'vk.com/emoji/e/'+str(number)+'e283a3.png" style="'+IMG_STYLE+'">'


def page(markup=None):
    if markup is None:
        markup = (FRAME + '<div id="xdget123" data-xdget-id="123"><p>Before '+image(1)+' first '
                  '<a href="https://example.test/material">Keep link</a></p><p>'+image(2)+' second '
                  '<mark style="'+MARK_STYLE+'">Highlighted teaching text</mark><br /></p><p>'+image(3)+' third.</p></div>')
    return {'name':'page','children':[{'id':'synthetic','name':'text','fields':{'html':markup},
            'style':{'lists':{'text':{'fontSize':{'value':{'number':18,'units':'px'}}}}}}]}


class Images(HTMLParser):
    def __init__(self):super().__init__();self.rows=[]
    def handle_starttag(self,tag,attrs):
        if tag=='img':self.rows.append((dict(attrs)['src'],self.get_starttag_text()))


def bind(ape):
    node=ape['children'][0];source=node['fields']['html'];parser=Images();parser.feed(source)
    record={'ape_sha256':subject._digest(ape),'node_sha256':subject._digest(node),
            'html_sha256':hashlib.sha256(source.encode()).hexdigest(),
            'style_sha256':subject._digest(node.get('style')),
            'markers':[{'src_sha256':hashlib.sha256(src.encode()).hexdigest(),
                        'tag_sha256':hashlib.sha256(tag.encode()).hexdigest(),'text':str(i)}
                       for i,(src,tag)in enumerate(parser.rows,1)]}
    return patch.object(subject,'BINDINGS',{(130,369):record})


def normalize(ape,context=(130,369)):
    return subject.normalize_reviewed_keycap_lesson(ape,*context,static_validator())


class KeycapLessonTests(unittest.TestCase):
    def test_exact_owner_digits_keep_source_video_links_text_order_and_mark_format(self):
        ape=page();before=copy.deepcopy(ape)
        with bind(ape):
            result,changes=normalize(ape)
            self.assertEqual(normalize(ape),(result,changes))
        self.assertEqual(ape,before)
        section=result['children'][0]
        self.assertEqual(section['style'],ape['children'][0]['style'])
        self.assertEqual([x['name']for x in section['children']],['video','text'])
        self.assertEqual(section['children'][0]['fields']['videoSrc'],'https://www.youtube.com/embed/abcdefghijk?rel=0')
        suffix=section['children'][1]['fields']['html']
        self.assertNotIn('<img',suffix);self.assertNotIn('\u20e3',suffix)
        self.assertLess(suffix.index('1 first'),suffix.index('2 second'))
        self.assertLess(suffix.index('2 second'),suffix.index('3 third'))
        self.assertIn('href="https://example.test/material"',suffix)
        self.assertIn('background: rgb(255, 214, 30)',suffix)
        self.assertIn('padding: 0.2rem 0.4rem',suffix);self.assertIn('line-height: 1',suffix)
        self.assertNotIn('border-radius',suffix);self.assertNotIn('display:',suffix)
        self.assertEqual(changes[0]['marker_text'],['1','2','3'])
        self.assertTrue(changes[0]['material_preserved_with_owner_digits'])
        self.assertNotIn('https://',json.dumps(changes))
        payload={'account':'mastervision','source_origin':'https://shop.mastervision.su','format':'ape',
                 'course_id':130,'lesson_id':369,'course_title':'Synthetic','lesson_title':'Synthetic','ape':result}
        plan=_core().plan_import(payload)
        self.assertTrue(plan['ready'],plan['issues'])
        self.assertEqual([x['type']for x in plan['blocks']],['videoChoice','htmlBlock'])

    def test_configured_source_hashes_fail_closed_and_other_lessons_are_unchanged(self):
        ape=page()
        with bind(ape):
            for context in ((130,370),(131,369)):
                self.assertEqual(normalize(ape,context),(ape,[]))
            for key in ('html','style','node','ape'):
                changed=copy.deepcopy(ape)
                if key=='html':changed['children'][0]['fields']['html']+=' changed'
                if key=='style':changed['children'][0]['style']['extra']='meaningful'
                if key=='node':changed['children'][0]['id']='changed'
                if key=='ape':changed['children'].append({'name':'text','fields':{'html':'Keep'}})
                with self.subTest(key=key),self.assertRaisesRegex(Review,'source_changed'):normalize(changed)
        with patch.object(subject,'ACCOUNT','mv-centr'):
            with self.assertRaisesRegex(Review,'account_mismatch'):normalize(ape)

    def test_unknown_settings_children_and_material_styles_are_never_discarded(self):
        for category in ('condition','anchor','child','caption','future'):
            ape=page();node=ape['children'][0]
            if category=='condition':node['fields']['visibleConditions']={'purchase':1}
            if category=='anchor':node['fields']['anchor']='keep'
            if category=='child':node['children']=[{'name':'text','fields':{'html':'Keep'}}]
            if category=='caption':node['style']['caption']='Keep'
            if category=='future':node['future']='Keep'
            with self.subTest(category=category),bind(ape),self.assertRaises(Review):normalize(ape)

    def test_owner_mapping_cannot_authorize_meaningful_alt_or_other_image_settings(self):
        for fragment in (' alt="Diagram"',' onload="run()"',' width="200"',' src="https://example.test/x.png"'):
            ape=page();source=ape['children'][0]['fields']['html']
            ape['children'][0]['fields']['html']=source.replace(image(1),image(1).replace('>',fragment+'>'))
            with self.subTest(fragment=fragment),bind(ape),self.assertRaises(Review):normalize(ape)

    def test_order_marker_count_and_known_mark_properties_are_strict(self):
        source=page()['children'][0]['fields']['html']
        variants=(source.replace(image(1),image(2),1),source.replace(image(3),''),
                  source.replace('display: inline-block','display: none'),
                  source.replace('border-radius: 4px','border-radius: 8px'),
                  source.replace('line-height: 1','content: hidden'),
                  source.replace('vk.com/emoji/e/1e283a3','example.test/emoji/e/1e283a3'))
        for value in variants:
            ape=page(value)
            with self.subTest(value=value[-40:]),bind(ape),self.assertRaises(Review):normalize(ape)

    def test_iframe_prefix_cannot_hide_content_or_unsupported_video(self):
        source=page()['children'][0]['fields']['html']
        for value in ('Keep '+source,source.replace('www.youtube.com','example.test'),
                      source.replace('frameborder="0"','frameborder="0" onload="run()"'),
                      source.replace('</iframe>','Visible fallback</iframe>',1)):
            ape=page(value)
            with bind(ape),self.assertRaises(Review):normalize(ape)

    def test_public_binding_is_only_four_source_hashes_three_tag_hashes_and_digits(self):
        self.assertEqual(set(subject.BINDINGS),{(130,369)})
        record=subject.BINDINGS[(130,369)]
        self.assertEqual([x['text']for x in record['markers']],['1','2','3'])
        self.assertNotIn('https://',repr(record))
        for key in ('ape_sha256','node_sha256','html_sha256','style_sha256'):
            self.assertEqual(len(record[key]),64)


if __name__=='__main__':unittest.main()

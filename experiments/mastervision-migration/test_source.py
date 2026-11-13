"""Synthetic source observations only: no accounts, files, browser or network."""
import base64
import copy
import json
import unittest
from unittest.mock import patch
import zlib

import source


def catalog(*, next_page=2, origin=source.ORIGIN, total=3, start=1, end=2):
    return '<div id="training-grid"><div class="summary">Элементы %d—%d из %d.</div><table><tbody>' % (start,end,total) + ''.join(
        '<tr><td><a href="%s%s?id=%d&amp;lg=ru">Course %d</a><a href="%s?id=%d">✎</a></td></tr>' %
        (origin,source.COURSE,n,n,source.COURSE,n) for n in (7,9)) + \
        '</tbody></table><div class="pager"><a href="%s?TrainingSearch_page=%s">Следующая &gt;</a></div></div>' % (source.CATALOG,next_page)


def leaf(ident=11, course=7):
    return {'id_training_lessons':ident,'id_training':course,'training_lessons':'Lesson '+str(ident),
            'links':{'update':source.LESSON+'?id='+str(ident)+'&lg=ru'},'unknown':{'future_setting':[True,None,3]}}


def course(tree=None, extra='', action=True):
    tree = [leaf(), {'group':'Later','children':[leaf(12)]}] if tree is None else tree
    return '<img src="/avatar.png"><form%s><input name="TrainingForm[id_training]" value="7">' % (
        ' action="'+source.COURSE+'?id=7&amp;lg=ru"' if action else '') + \
        '<input name="TrainingForm[training]" value="Course &amp; title">' + extra + '</form>' + \
        '<script>AWO.training.LessonsEditor("#editor", {"trainingLessonsTree":'+json.dumps(tree)+'});</script>'


def lesson(ape=None, extra='', action=True):
    if ape is None: ape={'name':'page','children':[{'name':'columns','fields':{'unknown':[1,None]},'children':[
        {'name':'text','fields':{'html':'Hello {name} <b>world</b>'}}]}]}
    packed=base64.b64encode(zlib.compress(json.dumps(ape).encode())).decode()
    return '<a href="'+source.COURSE+'?id=7&amp;lg=ru">Course</a><form%s>' % (
        ' action="'+source.LESSON+'?id=11&amp;lg=ru"' if action else '') + \
        '<input name="TrainingLessons[training_lessons]" value="Lesson 11">'+extra+'</form>' + \
        '<script>AWO.APE("#TrainingLessons_description_ape", {formatVersion:4,packed:true,block:'+json.dumps(packed)+'});</script>'


class CatalogTests(unittest.TestCase):
    def test_all_rows_titles_and_next(self):
        out=source.parse_catalog(catalog())
        self.assertEqual((out['total'],out['start'],out['end']),(3,1,2))
        self.assertEqual([x['id'] for x in out['courses']],[7,9])
        self.assertEqual(out['courses'][0]['title'],'Course 7')
        self.assertEqual(out['next_url'],source.ORIGIN+source.CATALOG+'?TrainingSearch_page=2')

    def test_hidden_next_ignored_on_last_page(self):
        self.assertIsNone(source.parse_catalog(catalog(total=2))['next_url'])

    def test_bad_count_duplicate_and_next_rejected(self):
        for page in (catalog(end=3),catalog().replace('id=9','id=7'),catalog(next_page=8)):
            with self.assertRaises(source.Review):source.parse_catalog(page)

    def test_mvc_editor_never_accepted(self):
        with self.assertRaisesRegex(source.Review,'identity_mismatch'):
            source.parse_catalog(catalog(origin='https://shop.mv-centr.ru'))

    def test_missing_grid_and_invalid_page_rejected(self):
        for value,page in [('<h1>Login</h1>',1),(catalog(),True),(catalog(),0)]:
            with self.assertRaises(source.Review):source.parse_catalog(value,page)


class AuthenticationTests(unittest.TestCase):
    def test_inline_login_form_is_fatal_even_with_http_200(self):
        pages = [
            '<form id="login-form" action="/site/login"><input name="LoginForm[username]">'
            '<input type="password" name="LoginForm[password]"></form>',
            '<form action="/login"><input type="email" name="email"><input type="password" name="password"></form>',
            '<form id="login-form"><input name="LoginForm[code]"></form>',
        ]
        parsers = [source.parse_catalog, lambda html: source.parse_course(html, 7),
                   lambda html: source.parse_lesson(html, 7, 11, 'Course', 'Lesson')]
        for html in pages:
            for parser in parsers:
                with self.subTest(parser=parser.__name__), self.assertRaisesRegex(source.Review, '^source_auth_error$'):
                    parser(html)

    def test_course_settings_and_login_links_are_not_authentication_failures(self):
        extra = '<input type="password" name="TrainingForm[password]">' \
                '<a href="/site/login">Login</a><script>const sample = \'<form id="login-form">\';</script>'
        self.assertEqual(source.parse_course(course(extra=extra), 7)['lesson_ids'], [11, 12])
        self.assertEqual(source.parse_catalog(catalog() + '<a href="/login">Login</a>')['total'], 3)


class CourseTests(unittest.TestCase):
    def test_tree_order_raw_values_and_form_settings_preserved(self):
        extra='<input type="hidden" name="future" value="0"><input type="checkbox" name="future" checked value="1">' \
              '<textarea name="other">&lt;b&gt;Raw {name}&lt;/b&gt;</textarea>' \
              '<select name="newtype" multiple><option value="a" selected>A</option><option>B</option></select>'
        out=source.parse_course(course(extra=extra),7)
        self.assertEqual(out['title'],'Course & title')
        self.assertEqual(out['lesson_ids'],[11,12])
        self.assertEqual(out['lessons'][0]['raw'],leaf())
        self.assertEqual(out['tree'][1]['children'][0],leaf(12))
        fields=out['settings']
        self.assertEqual([x['value'] for x in fields if x['attrs'].get('name')=='future'],['0','1'])
        self.assertIn('checked',fields[3]['attrs'])
        self.assertEqual(fields[4]['value'],'<b>Raw {name}</b>')
        self.assertIn('selected',fields[5]['options'][0]['attrs'])
        self.assertIsNone(out['cover_url'])

    def test_empty_only_when_literal_tree_is_explicitly_empty(self):
        out=source.parse_course(course([]),7)
        self.assertEqual(out['lesson_ids'],[])
        self.assertEqual(out['empty_reason'],'empty_course_tree')
        with self.assertRaisesRegex(source.Review,'unrecognized_empty'):
            source.parse_course(course([{'unknown':'not a confirmed empty tree'}]),7)

    def test_duplicates_wrong_course_nested_wrong_link_rejected(self):
        bad_link=leaf();bad_link['links']['update']='https://shop.mv-centr.ru'+source.LESSON+'?id=11'
        for tree in ([leaf(),leaf()],[{'group':'x','children':[leaf(course=99)]}],[bad_link]):
            with self.assertRaises(source.Review):source.parse_course(course(tree),7)

    def test_ids_and_titles_must_match_confirmed_form(self):
        for page in (course().replace('value="7"','value="8"'),course().replace('id=7&amp;lg=ru','id=8&amp;lg=ru')):
            with self.assertRaisesRegex(source.Review,'identity_mismatch'):source.parse_course(page,7)

    def test_non_json_javascript_and_duplicate_keys_rejected(self):
        prefix=course([]).replace('"trainingLessonsTree":[]','"trainingLessonsTree":REPLACE')
        for value in ('[dangerous()]',"[{'id_training_lessons':11,'id_training_lessons':12}]",'[undefined]'):
            with self.assertRaises(source.Review):source.parse_course(prefix.replace('REPLACE',value),7)

    def test_single_quoted_js_literals_supported(self):
        page=course([]).replace('"trainingLessonsTree":[]',"'trainingLessonsTree':[{'id_training_lessons':11,'id_training':7,'training_lessons':'Lesson 11','links':{'update':'/shop/training/traininglessons/admin/update?id=11'},'x':true,'y':null}]")
        out=source.parse_course(page,7)
        self.assertIs(out['lessons'][0]['raw']['x'],True)
        self.assertIsNone(out['lessons'][0]['raw']['y'])

    def test_only_confirmed_cover_fields_or_widgets(self):
        out=source.parse_course(course(extra='<img id="avatar" src="/other.png"><input name="TrainingForm[image]" value="https://cdn.example.test/cover.png">'),7)
        self.assertEqual(out['cover_url'],'https://cdn.example.test/cover.png')
        out=source.parse_course(course(extra='<img id="TrainingForm_cover" src="/cover.png">'),7)
        self.assertEqual(out['cover_url'],source.ORIGIN+'/cover.png')
        with self.assertRaisesRegex(source.Review,'cover_ambiguous'):
            source.parse_course(course(extra='<input name="TrainingForm[image]" value="/a"><img id="TrainingForm_cover" src="/b">'),7)

    def test_course_image_row_current_crop_widget_excludes_new_preview(self):
        current='<div id="yii_rcrop_0_currentImage" class="current-image-wrap"><img src="https://f1.autoweboffice.com/synthetic-cover.jpg"></div>'
        extra='<table><tr><td><label for="TrainingForm_image">Cover</label></td><td>'+current+ \
              '<div id="yii_rcrop_0_newImage" class="new-image-wrap"><img src="data:image/png;base64,PREVIEW"></div></td></tr></table>'
        out=source.parse_course(course(extra=extra),7)
        self.assertEqual(out['cover_url'],'https://f1.autoweboffice.com/synthetic-cover.jpg')

    def test_crop_widget_in_other_row_or_outside_editor_is_not_cover(self):
        widget='<div id="yii_rcrop_0_currentImage" class="current-image-wrap"><img src="https://f1.autoweboffice.com/avatar.jpg"></div>'
        extra='<table><tr><td><label for="TrainingForm_image">Cover</label></td></tr><tr><td>'+widget+'</td></tr></table>'
        self.assertIsNone(source.parse_course(course(extra=extra),7)['cover_url'])
        outside='<tr><td><label for="TrainingForm_image">Other form</label>'+widget+'</td></tr>'
        self.assertIsNone(source.parse_course(course()+outside,7)['cover_url'])

    def test_crop_cover_must_be_unique_and_https(self):
        prefix='<table><tr><td><label for="TrainingForm_image">Cover</label>'
        suffix='</td></tr></table>'
        widget='<div id="yii_rcrop_0_currentImage" class="current-image-wrap">%s</div>'
        for images in ('<img src="https://f1.autoweboffice.com/a.jpg"><img src="https://f1.autoweboffice.com/b.jpg">',
                       '<img src="javascript:alert(1)">','<img src="http://f1.autoweboffice.com/a.jpg">'):
            with self.assertRaises(source.Review):source.parse_course(course(extra=prefix+(widget%images)+suffix),7)
        out=source.parse_course(course(extra=prefix+(widget%'')+suffix),7)
        self.assertIsNone(out['cover_url'])


class LessonTests(unittest.TestCase):
    def conditions_page(self, option='visibleConditionsTypes:{"purchaseGoods":1}'):
        before, after = lesson().rsplit('});</script>', 1)
        return before + ',' + option + '});</script>' + after

    def test_absent_page_children_adds_only_reversible_empty_list(self):
        ape={'id':'page-uuid','name':'page','fields':{'commonFontName':'Arial',
             'commonFontLink':'https://fonts.googleapis.com/css?family=Arial'},
             'style':{'lists':{'container':{'paddingTop':{'value':{'number':0,'units':'px'}}}}}}
        before=copy.deepcopy(ape)
        out=source.parse_lesson(lesson(ape),7,11,'Course','Lesson 11')
        self.assertEqual(ape,before)
        self.assertEqual(out['payload']['ape'],{**ape,'children':[]})
        self.assertIs(out['ape_root_children_defaulted'],True)
        reconstructed=copy.deepcopy(out['payload']['ape']);reconstructed.pop('children')
        self.assertEqual(reconstructed,ape)
        self.assertNotIn('empty_reason',out)
        ordinary=source.parse_lesson(lesson({'name':'page','children':[]}),7,11,'Course','Lesson 11')
        self.assertNotIn('ape_root_children_defaulted',ordinary)

    def test_unknown_nonempty_root_material_is_preserved_and_not_claimed_ready(self):
        ape={'name':'page','fields':{'html':'<p>Unknown authored material.</p>'},
             'style':{'caption':'Keep style material'}}
        out=source.parse_lesson(lesson(ape),7,11,'Course','Lesson 11')
        self.assertEqual(out['payload']['ape'],{**ape,'children':[]})
        self.assertNotIn('empty_reason',out)
        self.assertNotIn('ready',out)

    def test_explicit_null_nonlist_or_nonpage_roots_are_never_defaulted(self):
        for ape in ({'name':'page','children':None},{'name':'page','children':{}},
                    {'name':'page','children':'not empty'},{'name':'section'},[], 'unknown'):
            with self.subTest(ape=ape),self.assertRaisesRegex(source.Review,'^ape_(?:root|payload)_unrecognized$'):
                source.parse_lesson(lesson(ape),7,11,'Course','Lesson 11')

    def test_exact_visible_conditions_option_retains_payload_and_editor_option(self):
        ordinary=source.parse_lesson(lesson(),7,11,'Course','Lesson 11')
        for key in ('visibleConditionsTypes',"'visibleConditionsTypes'",'"visibleConditionsTypes"'):
            for purchase in ('purchaseGoods',"'purchaseGoods'",'"purchaseGoods"'):
                out=source.parse_lesson(self.conditions_page(key+':{'+purchase+':7}'),7,11,'Course','Lesson 11')
                self.assertEqual(out['payload'],ordinary['payload']);self.assertEqual(out['settings'],ordinary['settings'])
                self.assertEqual(out['editor_options'],{'visibleConditionsTypes':{'purchaseGoods':7}})
        self.assertNotIn('editor_options',ordinary)

    def test_conditions_duplicate_unknown_expression_or_wrong_type_is_rejected(self):
        options=(
            'visibleConditionsTypes:{purchaseGoods:1,purchaseGoods:2}',
            'visibleConditionsTypes:{purchaseGoods:1},visibleConditionsTypes:{purchaseGoods:2}',
            'visibleConditionsTypes:{purchaseGoods:1,other:2}',
            'visibleConditionsTypes:{other:1}', 'visibleConditionsTypes:[1]',
            'visibleConditionsTypes:{purchaseGoods:true}', 'visibleConditionsTypes:{purchaseGoods:null}',
            'visibleConditionsTypes:{purchaseGoods:"1"}', 'visibleConditionsTypes:{purchaseGoods:-1}',
            'visibleConditionsTypes:{purchaseGoods:1.5}', 'visibleConditionsTypes:{purchaseGoods:2147483648}',
            'visibleConditionsTypes:{purchaseGoods:99999999999}',
            'visibleConditionsTypes:{purchaseGoods:dangerous()}',
            'visibleConditionsTypes:{purchaseGoods:1+1}', 'otherOption:{purchaseGoods:1}',
            'visibleConditionsTypes:{purchaseGoods:1},otherOption:2',
        )
        for option in options:
            with self.subTest(option=option),self.assertRaises(source.Review):
                source.parse_lesson(self.conditions_page(option),7,11,'Course','Lesson 11')

    def test_conditions_malformed_brackets_keys_and_duplicate_primary_options_rejected(self):
        good=self.conditions_page()
        pages=(good.replace('purchaseGoods":1}','purchaseGoods":1]'),
               good.replace('visibleConditionsTypes:', '"visibleConditionsTypes\':'),
               good.replace('formatVersion:4,','formatVersion:4,formatVersion:4,'),
               good.replace('packed:true,','packed:true,packed:true,'),
               good.replace('formatVersion:4,','"formatVersion\':4,'))
        for page in pages:
            with self.subTest(page=page[-80:]),self.assertRaises(source.Review):
                source.parse_lesson(page,7,11,'Course','Lesson 11')

    def test_second_malformed_target_call_cannot_hide_behind_one_valid_call(self):
        malformed='<script>AWO.APE("#TrainingLessons_description_ape", {unknown:dangerous()});</script>'
        extended=self.conditions_page()
        extra_script='<script>'+extended.split('<script>',1)[1]
        for page in (lesson()+malformed,extended+malformed,lesson()+extra_script):
            with self.assertRaisesRegex(source.Review,'^ape_payload_missing_or_ambiguous$'):
                source.parse_lesson(page,7,11,'Course','Lesson 11')
        other=malformed.replace('TrainingLessons_description_ape','Other_editor')
        self.assertEqual(source.parse_lesson(lesson()+other,7,11,'Course','Lesson 11'),
                         source.parse_lesson(lesson(),7,11,'Course','Lesson 11'))

    def test_extended_option_still_requires_original_source_identity(self):
        page=self.conditions_page()
        for changed in (page.replace(source.COURSE+'?id=7',source.COURSE+'?id=8'),
                        page.replace(source.LESSON+'?id=11',source.LESSON+'?id=12'),
                        page.replace(source.COURSE+'?id=7','https://shop.mv-centr.ru'+source.COURSE+'?id=7')):
            with self.assertRaisesRegex(source.Review,'source_identity_mismatch'):
                source.parse_lesson(changed,7,11,'Course','Lesson 11')

    def test_payload_exact_ape_and_all_settings(self):
        ape={'name':'page','children':[{'name':'future-block','fields':{'newType':[1,False,None,'{name}']}}]}
        out=source.parse_lesson(lesson(ape,extra='<input name="future" type="future-widget" value="raw">'),7,11,'Course & title','Lesson 11')
        self.assertEqual(out['payload'],{'account':'mastervision','source_origin':source.ORIGIN,'course_id':7,'lesson_id':11,
            'course_title':'Course & title','lesson_title':'Lesson 11','format':'ape','ape':ape})
        self.assertEqual(out['settings'][1]['attrs']['type'],'future-widget')

    def test_own_id_hidden_alternative_and_missing_id_rejected(self):
        extra='<input name="TrainingLessons[id_training_lessons]" value="11">'
        self.assertEqual(source.parse_lesson(lesson(extra=extra,action=False),7,11,'Course','Lesson 11')['payload']['lesson_id'],11)
        with self.assertRaisesRegex(source.Review,'lesson_identity_unconfirmed'):
            source.parse_lesson(lesson(action=False),7,11,'Course','Lesson 11')

    def test_wrong_account_course_lesson_and_changed_title_rejected(self):
        cases=[lesson().replace(source.COURSE+'?id=7',source.ORIGIN.replace('mastervision.su','mv-centr.ru')+source.COURSE+'?id=7'),
               lesson().replace(source.COURSE+'?id=7',source.COURSE+'?id=8'),
               lesson().replace(source.LESSON+'?id=11',source.LESSON+'?id=12')]
        for page in cases:
            with self.assertRaises(source.Review):source.parse_lesson(page,7,11,'Course','Lesson 11')
        with self.assertRaisesRegex(source.Review,'title_changed'):
            source.parse_lesson(lesson(),7,11,'Course','Different title')

    def test_truncated_duplicate_unpacked_and_wrong_root_rejected(self):
        page=lesson()
        for bad in (page+page,page.replace('packed:true','packed:false'),page.replace('block:"','block:"!'),
                    lesson({'name':'not-page','children':[]}),lesson({'name':'page','children':[{'name':'text','fields':[]}]})):
            with self.assertRaises(source.Review):source.parse_lesson(bad,7,11,'Course','Lesson 11')

    def test_fixed_config_cannot_change_to_other_account(self):
        with self.assertRaisesRegex(source.Review,'wrong_account_origin'):
            source.Config(origin='https://shop.mv-centr.ru')
        with patch.object(source,'ACCOUNT','mv-centr'):
            with self.assertRaisesRegex(source.Review,'wrong_account_origin'):source.parse_catalog(catalog())

    def test_wrong_hidden_course_and_excessive_html_depth_rejected(self):
        with self.assertRaisesRegex(source.Review,'identity_mismatch'):
            source.parse_lesson(lesson(extra='<input name="TrainingLessons[id_training]" value="99">'),7,11,'Course','Lesson 11')
        with self.assertRaisesRegex(source.Review,'depth_exceeded'):
            source.parse_catalog('<div>'*300+catalog()+'</div>'*300)


if __name__=='__main__':unittest.main()

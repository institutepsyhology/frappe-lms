import copy
import hashlib
import unittest
from unittest.mock import patch

import import_capture
import normalize_iomp_course_material as material


def record(course, lesson, nodes):
    return {'account': 'iomp', 'source_origin': 'https://shop.iomp.ru', 'format': 'ape',
            'course_id': course, 'lesson_id': lesson, 'course_title': 'Test', 'lesson_title': 'Lesson',
            'ape': {'name': 'page', 'children': nodes}}


def button(label, url=''):
    return {'id': 'source-button', 'name': 'button', 'fields': {'html': label, 'url': url, 'linkType': 'url',
            'anchor': '', 'toAnchor': '', 'event': '', 'icon': '', 'blank': True}, 'children': []}


class IompCourseMaterialTests(unittest.TestCase):
    def test_only_valid_single_player_urls_lose_outer_whitespace(self):
        youtube = 'https://youtu.be/abcdefghijk'
        rutube = 'https://rutube.ru/video/private/' + 'a' * 32 + '/?p=test_key'
        fields = {'videoProvider': 'youtube', 'videoSrc': ' ' + youtube,
                  'videoProvider2': 'rutube', 'videoSrc2': rutube + '\n'}
        source = record('134', '2022', [{'name': 'video', 'fields': fields}])
        material.normalize_iomp_course_material(source)
        self.assertEqual((fields['videoSrc'], fields['videoSrc2']), (youtube, rutube))
        for invalid in (' ' + youtube + ' ' + youtube, ' https://example.com/video', ' ' + rutube):
            fields['videoSrc'] = invalid
            material.normalize_iomp_course_material(source)
            self.assertEqual(fields['videoSrc'], invalid)

    def test_clipboard_metadata_removal_preserves_text_style_and_links(self):
        attr = ' class="docData;DOCY;v5;3;YWJj"'
        paragraph = '<p style="text-align:justify"' + attr + '><b>00:15</b> <a href="https://example.com/">Материал</a></p>'
        source = '<p>Вступление</p>\n' + paragraph + paragraph
        self.assertEqual(material._remove_clipboard_classes(source), source.replace(attr, ''))
        pasted = paragraph.replace('<b>00:15</b>', '<span style="tab-stops:12.322527777777777cm">00:15</span>')
        self.assertEqual(material._remove_clipboard_classes(pasted),
                         pasted.replace(attr, '').replace(' style="tab-stops:12.322527777777777cm"', ''))
        for changed in (paragraph.replace(';3;', ';7;'), paragraph.replace('<p ', '<div ').replace('</p>', '</div>'),
                        paragraph.replace('<b>', '<script>').replace('</b>', '</script>')):
            self.assertEqual(material._remove_clipboard_classes(changed), changed)

    def test_multiline_heading_keeps_its_level_and_authored_break(self):
        node = {'name': 'header-simple', 'fields': {'level': 'h5', 'html': 'Начало<br>продолжение'}}
        source = record('322', '5943', [copy.deepcopy(node)])
        material.normalize_iomp_course_material(source)
        self.assertEqual(import_capture.plan_import(source)['blocks'][0]['data']['text'],
                         '<h5>Начало<br>продолжение</h5>')
        node['fields']['anchor'] = 'important'
        source = record('322', '5943', [copy.deepcopy(node)])
        material.normalize_iomp_course_material(source)
        self.assertEqual(source['ape']['children'], [node])

    def test_shared_timing_panel_keeps_heading_and_body_and_skips_mixed_panels(self):
        body = {'name': 'text', 'fields': {'html': '<p>00:15 Начало</p>'}}
        item = {'name': 'unfolding-item', 'fields': {'headerHtml': '<strong>Тайминг</strong>'}, 'children': [body]}
        panel = {'name': 'unfolding', 'fields': {'onlyOneExpanded': True, 'initialState': 'all-folded',
                 'expandedSpeedRate': 1}, 'children': [item]}
        source = record('167', '2954', [copy.deepcopy(panel)])
        material.normalize_iomp_course_material(source)
        children = source['ape']['children'][0]['children'][0]['children']
        self.assertEqual(children[0]['fields']['html'], item['fields']['headerHtml'])
        self.assertEqual(children[1:], [body])
        other = copy.deepcopy(panel)
        other['children'][0]['fields']['headerHtml'] = 'Меню'
        source = record('167', '2954', [copy.deepcopy(panel), copy.deepcopy(other)])
        material.normalize_iomp_course_material(source)
        self.assertEqual(source['ape']['children'], [panel, other])

    def test_supervision_material_labels_keep_original_links_and_numbers(self):
        for original, expected in material.SUPERVISION_CAPTIONS.items():
            with self.subTest(original=original):
                node = button(original, 'https://example.com/audio')
                source = record('305', '5834', [copy.deepcopy(node)])
                foreign = record('304', '5758', [copy.deepcopy(node)])
                foreign['source_origin'] = 'https://shop.mastervision.su'
                material.normalize_iomp_course_material(source)
                material.normalize_iomp_course_material(foreign)
                self.assertEqual(foreign['ape']['children'], [node])
                node['fields']['html'] = expected
                self.assertEqual(source['ape']['children'], [node])
                self.assertFalse(import_capture.plan_import(source)['issues'])

    def test_only_inert_avatar_is_removed_and_neighboring_content_survives(self):
        avatar = {'name': 'image', 'fields': {'imageSrc': '{avatar_url}', 'linkHref': '', 'anchor': ''}}
        linked = copy.deepcopy(avatar)
        linked['fields']['linkHref'] = 'https://example.com/resource'
        styled = {**avatar, 'style': {'caption': 'Учебная иллюстрация'}}
        text = {'name': 'text', 'fields': {'html': '<p>Материалы урока</p>'}}
        image = {'name': 'image', 'fields': {'imageSrc': 'https://example.com/picture.jpg'}}
        column = {'name': 'column', 'children': [avatar, text, linked, styled, image]}
        source = record('304', '5737', [copy.deepcopy(column)])
        foreign = copy.deepcopy(source)
        foreign['account'] = 'mastervision'
        import_capture.normalize_review(source)
        import_capture.normalize_review(foreign)
        self.assertEqual(source['ape']['children'][0]['children'], [text, linked, styled, image])
        self.assertEqual(foreign['ape']['children'], [column])

    def test_third_empty_button_omission_preserves_links_and_rejects_drift(self):
        empty = button('АУДИОЗАПИСЬ 3')
        digest = material._digest({k: v for k, v in empty.items() if k != 'id'})
        changed = copy.deepcopy(empty)
        changed['fields']['event'] = 'custom'
        linked = button('АУДИОЗАПИСЬ 3', 'https://example.com/audio')
        other = button('АУДИОЗАПИСЬ 2')
        for identity in [('131', '2093'), ('152', '2411'), ('341', '6817'), ('152', '2093')]:
            with self.subTest(identity=identity), patch.object(material, 'EMPTY_BUTTON_DIGEST', digest):
                nodes = [other, empty, changed, linked]
                source = record(*identity, copy.deepcopy(nodes))
                material.normalize_iomp_course_material(source)
                self.assertEqual(source['ape']['children'], [other, changed, linked] if identity in
                                 material.EMPTY_THIRD_AUDIO else nodes)

    def test_button_normalization_retains_url_and_native_settings(self):
        for identity, (original, expected) in material.DECORATED_LABELS.items():
            node = button(original, 'https://example.com/source')
            source = record(*identity, [copy.deepcopy(node)])
            material.normalize_iomp_course_material(source)
            node['fields']['html'] = expected
            self.assertEqual(source['ape']['children'], [node])
            self.assertFalse(import_capture.plan_import(source)['issues'])

    def test_numbered_timing_lists_retain_zero_padding_and_order(self):
        html = ('<ol><li style="list-style-type:decimal-leading-zero" aria-level="1">Intro</li></ol>'
                '<ol start="9"><li style="list-style-type:decimal-leading-zero" aria-level="2">Work</li></ol>')
        source = record('152', '2401', [{'name': 'text', 'fields': {'html': html}}])
        with patch.object(material, 'TIMING_LIST_DIGEST', hashlib.sha256(html.encode()).hexdigest()):
            material.normalize_iomp_course_material(source)
            once = copy.deepcopy(source)
            material.normalize_iomp_course_material(source)
        self.assertEqual(source, once)
        self.assertEqual(source['ape']['children'][0]['fields']['html'],
                         '<ol><li style="list-style:none" aria-level="1">01. Intro</li></ol>'
                         '<ol start="9"><li style="list-style:none" aria-level="2">09. Work</li></ol>')
        self.assertFalse(import_capture.plan_import(source)['issues'])

    def test_accordion_keeps_its_heading_before_timestamps(self):
        heading = '<strong>ТАЙМИНГ</strong>'
        body = {'name': 'text', 'fields': {'html': '<p>0:01 Intro</p>'}}
        item = {'name': 'unfolding-item', 'fields': {'headerHtml': heading}, 'children': [body]}
        accordion = {'name': 'unfolding', 'fields': {'onlyOneExpanded': True, 'initialState': 'all-folded',
                     'expandedSpeedRate': 1}, 'children': [item]}
        source = record('131', '2183', [accordion])
        material.normalize_iomp_course_material(source)
        children = source['ape']['children'][0]['children'][0]['children']
        self.assertEqual(children[0]['fields']['html'], heading)
        self.assertEqual(children[1:], [body])
        self.assertFalse(import_capture.plan_import(source)['issues'])

    def test_reviewed_term_uses_plain_text_and_keeps_quotes_and_punctuation(self):
        html = '<p>что такое&nbsp;<code>&laquo;психосоматоз&raquo;</code>.<br />Далее</p>'
        node = {'name': 'text', 'fields': {'html': html}}
        source = record('163', '2683', [copy.deepcopy(node)])
        other_course = record('208', '3526', [copy.deepcopy(node)])
        changed = copy.deepcopy(source)
        changed['ape']['children'][0]['fields']['html'] += '<code>2 + 2</code>'
        original = copy.deepcopy(changed)
        with patch.object(material, 'PSYCHOSOMATOSIS_TEXT_DIGEST', hashlib.sha256(html.encode()).hexdigest()):
            material.normalize_iomp_course_material(source)
            material.normalize_iomp_course_material(other_course)
            material.normalize_iomp_course_material(changed)
        self.assertEqual(changed, original)
        self.assertEqual(source['ape'], other_course['ape'])
        self.assertEqual(source['ape']['children'][0]['fields']['html'],
                         '<p>что такое&nbsp;&laquo;психосоматоз&raquo;.<br />Далее</p>')
        self.assertFalse(import_capture.plan_import(source)['issues'])

    def test_other_site_is_untouched(self):
        original, _ = material.DECORATED_LABELS['152', '2385']
        source = record('152', '2385', [button(original, 'https://example.com')])
        source['source_origin'] = 'https://example.com'
        before = copy.deepcopy(source)
        material.normalize_iomp_course_material(source)
        self.assertEqual(source, before)

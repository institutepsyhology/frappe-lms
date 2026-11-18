import copy
import hashlib
import json
import unittest
from unittest.mock import patch

import import_capture  # Set up the shared migration modules' import paths.
import normalize_iomp_material as material
from normalize_inline_images import Content, normalize_inline_images


def payload(course, lesson, nodes):
    return {'account': 'iomp', 'source_origin': 'https://shop.iomp.ru', 'format': 'ape',
            'course_id': course, 'lesson_id': lesson, 'course_title': 'Course', 'lesson_title': 'Lesson',
            'ape': {'name': 'page', 'children': nodes}}


def bind(record, reviewed):
    material_fields = {key: value for key, value in reviewed.items() if key != 'id'}
    encoded = json.dumps(material_fields, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()
    return patch.dict(material.REVIEWED_NODES, {(record['course_id'], record['lesson_id']):
                                               hashlib.sha256(encoded).hexdigest()})


def content(markup):
    parsed = Content()
    parsed.feed(markup)
    return ''.join(parsed.text), parsed.links, parsed.images


class IompMaterialTests(unittest.TestCase):
    def test_manual_keeps_text_and_each_link_in_order(self):
        html = ('<div class="container"><a href="https://example.org/1">Part 1</a><br />'
                '<a href="https://example.org/2">Part 2</a></div><div class="talks-widget">&nbsp;</div>')
        node = {'id': 'text', 'name': 'text', 'fields': {'html': html}}
        record = payload('44', '243', [node])
        with bind(record, node):
            node['id'] = 'recaptured-id'
            material.normalize_iomp_material(record)
        cleaned = node['fields']['html']
        self.assertNotIn('talks-widget', cleaned)
        self.assertEqual(content(cleaned), content(html))

    def test_books_split_at_illustration_and_keep_other_material(self):
        image = 'https://example.org/picture.png'
        html = (f'<h1><a href="https://example.org/books">Books</a></h1><p><img src="{image}" /></p>'
                '<ul><li><a href="https://example.org/manual">Manual</a></li></ul>')
        node = {'id': 'source', 'name': 'text', 'fields': {'html': html}}
        sibling = {'id': 'video', 'name': 'video', 'fields': {'videoSrc': 'unchanged'}}
        record = payload('60', '342', [node, sibling])
        with bind(record, node):
            material.normalize_iomp_material(record)
            once = copy.deepcopy(record)
            material.normalize_iomp_material(record)
        first, picture, last, video = record['ape']['children']
        self.assertEqual(record, once)
        self.assertEqual([first['name'], picture['name'], last['name']], ['text', 'image', 'text'])
        self.assertEqual(picture['fields']['imageSrc'], image)
        self.assertEqual(content(first['fields']['html'] + last['fields']['html'])[:2], content(html)[:2])
        self.assertEqual(video, sibling)

    def test_static_text_with_two_inline_images_in_different_wrappers(self):
        first = 'https://f1.autoweboffice.ru/sample/first.jpg'
        second = 'https://f1.autoweboffice.ru/sample/second.jpg'
        source = (f'<p>Read</p><p><strong><img alt="" style="width: 620px; height: 87px;" src="{first}" />'
                  f'</strong></p><p>Answer the questions</p><p><img alt="" src="{second}" /></p>'
                  '<p>Send the assignment</p>')
        for course in ('7', '104', '141'):
            with self.subTest(course=course):
                node = {'name': 'text', 'fields': {'html': source}, 'id': 'new-id'}
                record = payload(course, '1234', [node])
                previous, _ = normalize_inline_images(record['ape'], material.make_html_block)
                material.normalize_iomp_material(record)
                self.assertEqual(record['ape'], previous)
                blocks = record['ape']['children']
                self.assertEqual([b['name'] for b in blocks], ['text', 'image', 'text', 'image', 'text'])
                self.assertEqual([b['fields']['imageSrc'] for b in blocks[1::2]], [first, second])
                self.assertEqual([content(b['fields']['html'])[0] for b in blocks[::2]],
                                 ['Read', 'Answer the questions', 'Send the assignment'])
                once = copy.deepcopy(record)
                material.normalize_iomp_material(record)
                self.assertEqual(record, once)

    def test_interactive_or_conditional_image_source_is_retained_for_review(self):
        image = '<p><img src="https://f1.autoweboffice.ru/sample/file.jpg"/></p>'
        html = '<p>Read</p>' + image + '<p>Answer</p>' + image + '<p>Done</p>'
        for kind, settings, style in [
            ('text', {'visibleConditions': ['condition']}, {}), ('text', {'anchor': 'chapter'}, {}),
            ('text', {}, {'caption': 'description'}), ('text', {}, {'display': 'none'}),
            ('header', {}, {}), ('code', {}, {}),
        ]:
            item = {'name': kind, 'fields': {'html': html, **settings}, 'style': style}
            record = payload('104', '1414', [item])
            original = copy.deepcopy(record)
            material.normalize_iomp_material(record)
            self.assertEqual(record, original)

    def test_unapproved_url_or_markup_stays_in_review(self):
        image = '<p><img src="https://f1.autoweboffice.ru/sample/a.jpg" /></p>'
        source = '<p>Read</p>' + image + '<p>Answer</p>' + image + '<p>Done</p>'
        for unsafe in (
            source.replace('.ru/sample', '.ru.example.org/sample'),
            source.replace('/sample/', '/%2e%2e/'), source.replace('.jpg', '.jpg?x=y'),
            source.replace('https://', 'http://'), source + '<script>bad</script>',
            source + '<iframe src="https://example.org/form"></iframe>',
            source.replace('<img ', '<img onclick="bad()" '), source.replace('<img ', '<img alt="caption" '),
            source.replace('<p><img', '<p>Caption <img'),
            source.replace('<p><img', '<p><a href="https://example.org/linked"><img').replace(' /></p>', ' /></a></p>'),
        ):
            node = {'name': 'text', 'id': 'item', 'fields': {'html': unsafe}}
            record = payload('130', '100', [node])
            before = copy.deepcopy(record)
            material.normalize_iomp_material(record)
            self.assertEqual(record, before)
            self.assertIn('unsafe_or_unrecognized_html', import_capture.plan_import(record)['issues'])

    def test_nested_mixed_siblings_keep_ready_html_and_original_image_ids(self):
        url = 'https://f1.autoweboffice.ru/sample/page.png'
        source = f'<p>Before</p><p><img src="{url}"/></p><p>Between</p><p><img src="{url}"/></p><p>After</p>'
        def leaf(ident):
            return {'name': 'text', 'id': ident, 'fields': {'html': source}}
        record = payload('130', '100', [{'name': 'section', 'children': [
            {'name': 'column', 'children': [leaf('first'), leaf('already-supported'), leaf('third')]},
        ]}])
        expected, _ = normalize_inline_images(record['ape'], material.make_html_block)
        all_split = expected['children'][0]['children'][0]['children']
        ready_node = copy.deepcopy(record['ape']['children'][0]['children'][0]['children'][1])
        original_plan = import_capture.plan_import
        def mixed_plan(probe, images=None):
            if [n.get('id') for n in probe['ape']['children']] == ['already-supported']:
                return {'issues': [], 'ready': True}
            return original_plan(probe, images)
        with patch.object(material, 'plan_import', side_effect=mixed_plan):
            material.normalize_iomp_material(record)
        self.assertEqual(record['ape']['children'][0]['children'][0]['children'],
                         [*all_split[:5], ready_node, *all_split[-5:]])

    def test_omits_only_bound_trainer_button_and_preserves_changed_button(self):
        button = {'id': 'question', 'name': 'button', 'fields': {'html': 'ЗААТЬ ВОПРОС ТРЕНЕРУ',
                                                                 'url': 'https://example.org/question'}}
        changed = copy.deepcopy(button)
        changed['fields']['url'] = 'https://example.org/assignment'
        homework = {'id': 'form', 'name': 'button', 'fields': {'html': 'ДОМАШНЕЕ ЗАДАНИЕ'}}
        record = payload('52', '336', [homework, changed, button])
        with bind(record, button):
            for key, value in [('course_id', '65'), ('lesson_id', '481'), ('account', 'mastervision'),
                               ('source_origin', 'https://example.org'), ('format', 'html')]:
                other = copy.deepcopy(record)
                other[key] = value
                before = copy.deepcopy(other)
                material.normalize_iomp_material(other)
                self.assertEqual(other, before)
            material.normalize_iomp_material(record)
        self.assertEqual(record['ape']['children'], [homework, changed])

    def test_exact_image_url_only(self):
        url = 'https://example.org/image.png'
        with patch.object(material, 'IMAGE_URL_DIGEST', hashlib.sha256(url.encode()).hexdigest()):
            self.assertTrue(material.reviewed_image_url(url))
            for value in [url + '?redirect=1', url + '#x', url.replace('https', 'http'), None]:
                self.assertFalse(material.reviewed_image_url(value))

import copy
import hashlib
import json
import unittest
from unittest.mock import patch

from importer import Review
from normalize_editor_nodes import _core
from normalize_inline_images import Content, normalize_inline_images
from normalize_source import static_validator
import normalize_reviewed_getcourse as subject


IMAGE = ('<img src="https://example.org/synthetic.jpg" alt="" '
         'style="box-sizing: border-box; border: 0px; vertical-align: middle; max-width: 100%; width: 217.5px;">')
HTML = ('<div class="xdget-block text-center" id="xdget7" data-xdget-id="7" style="box-sizing:border-box">'
        '<p dir="ltr">Keep every word &amp; <strong>emphasis</strong>.</p>'
        '<ol start="2"><li><p role="presentation">Second</p></li><li>Third</li></ol>'
        + IMAGE + '<p><a href="https://example.org/document?a=1&amp;b=2" target="_blank" title="Document">Material</a></p></div>')


def node(html=HTML):
    return {'id': 'synthetic-node', 'name': 'text', 'fields': {'anchor': '', 'html': html},
            'style': {'lists': {'text': {'paddingTop': {'value': {'number': 20, 'units': 'px'}}}}}}


def root(n): return {'name': 'page', 'children': [n]}


def binding(n, path=(0,), identity=(67, 101)):
    return patch.object(subject, 'BINDINGS', {identity: (path, subject._digest(n),
        hashlib.sha256(n['fields']['html'].encode()).hexdigest())})


def normalize(ape, identity=(67, 101)):
    return subject.normalize_reviewed_getcourse(ape, *identity, static_validator())


class ReviewedGetCourseTests(unittest.TestCase):
    def test_exact_source_keeps_text_links_images_formatting_and_list_semantics(self):
        source = root(node()); before = copy.deepcopy(source)
        with binding(source['children'][0]):
            prepared, changes = normalize(source)
            self.assertEqual(normalize(source), (prepared, changes))
            with self.assertRaisesRegex(Review, 'source_changed'): normalize(prepared)
        html = prepared['children'][0]['fields']['html']
        self.assertEqual(subject._signature(HTML), subject._signature(html))
        self.assertIn('start="2"', html)
        self.assertIn('role="presentation"', html)
        self.assertIn('width: 217.5px', html)
        self.assertIn('text-align:center', html)
        self.assertNotIn('id="xdget7"', html)
        self.assertNotIn('data-xdget-id', html)
        self.assertEqual(source, before)
        self.assertNotIn('http', json.dumps(changes))
        self.assertEqual(changes[0]['images'], 1)

    def test_existing_image_pipeline_extracts_images_in_original_order(self):
        source = root(node(HTML.replace(IMAGE, IMAGE + IMAGE.replace('synthetic.jpg', 'second.jpg'))))
        with binding(source['children'][0]): prepared, _ = normalize(source)
        extracted, changes = normalize_inline_images(prepared, static_validator())
        images = [n for n in extracted['children'] if n['name'] == 'image']
        self.assertEqual([n['fields']['imageSrc'] for n in images],
                         ['https://example.org/synthetic.jpg', 'https://example.org/second.jpg'])
        self.assertEqual(changes[0]['images'], 2)
        before, after = Content(), Content(); before.feed(source['children'][0]['fields']['html'])
        for n in extracted['children']:
            if n['name'] == 'text': after.feed(n['fields']['html'])
        self.assertEqual(before.text, after.text)
        self.assertEqual(before.links, after.links)
        payload = {'account': 'mastervision', 'source_origin': 'https://shop.mastervision.su', 'format': 'ape',
                   'course_id': 67, 'lesson_id': 101, 'course_title': 'Synthetic', 'lesson_title': 'Synthetic', 'ape': extracted}
        plan = _core().plan_import(payload, image_urls={n['id']: '/private/files/synthetic.jpg' for n in images})
        self.assertTrue(plan['ready'], plan['issues'])

    def test_image_only_resize_span_uses_existing_safe_wrapper_normalization(self):
        html = '<p><span id="docs-internal-guid-11111111-2222-3333-4444-555555555555"><span style="display:inline-block;height:199px">' + IMAGE + '</span></span></p>'
        source = root(node(html))
        with binding(source['children'][0]): prepared, changes = normalize(source)
        self.assertEqual(changes[0]['image_wrappers'], 1)
        self.assertEqual(subject._signature(html), subject._signature(prepared['children'][0]['fields']['html']))
        self.assertNotIn('display:inline-block', prepared['children'][0]['fields']['html'])
        extracted, _ = normalize_inline_images(prepared, static_validator())
        self.assertEqual(sum(n['name'] == 'image' for n in extracted['children']), 1)

    def test_generated_editor_attributes_are_not_authored_anchors(self):
        html = ('<div id="lite-block-live-wrapper-1234567890-7" data-block-id="7" data-updated="1234567890">'
                '<div id="ltBlock7" data-code="b-abcde" data-editable="true" data-main-class="header" data-param="header">'
                '<h2>Keep heading</h2></div></div>')
        n = node(html)
        with binding(n): prepared, changes = normalize(root(n))
        self.assertIn('<h2>Keep heading</h2>', prepared['children'][0]['fields']['html'])
        self.assertEqual(changes[0]['editor_attributes'], 6)
        for html in ('<div id="authored-anchor"><p>Keep</p></div>',
                     '<div id="xdget7"><a href="#xdget7">Keep</a></div>'):
            n = node(html)
            with self.subTest(html=html), binding(n), self.assertRaises(Review): normalize(root(n))

    def test_unrecognized_classes_editor_values_and_authored_metadata_are_not_removed(self):
        for html in ('<div class="hidden-unless-paid">Keep</div>',
                     '<div data-xdget-id="not-numeric">Keep</div>',
                     '<div data-editable="false">Keep</div>',
                     '<div data-main-class="authored-meaning">Keep</div>',
                     '<p data-custom="Keep metadata">Keep</p>',
                     '<div class="text-center" style="text-align:left">Keep</div>'):
            n = node(html)
            with self.subTest(html=html), binding(n), self.assertRaises(Review): normalize(root(n))

    def test_scripts_forms_embeds_comments_and_actions_are_never_dropped(self):
        for html in ('<script>Keep unknown script</script>', '<form><p>Keep form</p></form>',
                     '<iframe src="https://example.org/embed"></iframe>', '<style>p{color:red}</style>',
                     '<p><!-- Keep comment -->Text</p>', '<p onclick="bad()">Keep</p>',
                     '<p><a href="javascript:bad()">Keep link</a></p>'):
            n = node(html)
            with self.subTest(html=html), binding(n), self.assertRaises(Review): normalize(root(n))

    def test_unknown_or_meaningful_image_attributes_require_review(self):
        for image in (IMAGE.replace('border: 0px', 'border: 1px'),
                      IMAGE.replace('alt=""', 'alt="Meaningful caption"'),
                      IMAGE.replace('max-width: 100%', 'max-width: 75%'),
                      IMAGE.replace('src="', 'data-unknown="Keep" src="'),
                      IMAGE.replace('width: 217.5px', 'width: 217.5px; margin-left: 10px'),
                      IMAGE.replace('width: 217.5px', 'width: 217.5px; width: 220px')):
            n = node('<p>' + image + '</p>')
            with self.subTest(image=image), binding(n), self.assertRaises(Review): normalize(root(n))

    def test_matching_scope_changed_source_path_or_style_stops_immediately(self):
        original = node()
        with binding(original):
            variants = []
            n = copy.deepcopy(original); n['fields']['html'] += '<p>New material</p>'; variants.append(root(n))
            n = copy.deepcopy(original); n['style']['caption'] = 'New material'; variants.append(root(n))
            variants.append({'name': 'page', 'children': [{'name': 'section', 'children': [original]}]})
            variants.append({'name': 'page', 'children': []})
            for ape in variants:
                before = copy.deepcopy(ape)
                with self.subTest(ape=ape), self.assertRaisesRegex(Review, 'source_changed'): normalize(ape)
                self.assertEqual(ape, before)
        self.assertEqual(normalize(root(original), (68, 101)), (root(original), []))

    def test_conditions_delay_anchor_unknown_fields_and_children_are_preserved_for_review(self):
        nodes = []
        for key, value in [('visibleConditions', {'purchaseGoods': 7}), ('displayDelay', 30),
                           ('anchor', 'authored-anchor'), ('futureType', 'Keep')]:
            n = node(); n['fields'][key] = value; nodes.append(n)
        n = node(); n['children'] = [{'name': 'text', 'fields': {'html': 'Keep'}}]; nodes.append(n)
        for value in (None, False, 0, {}):
            n = node(); n['children'] = value; nodes.append(n)
        n = node(); n['style']['caption'] = 'Keep style material'; nodes.append(n)
        for n in nodes:
            with self.subTest(node=n), binding(n), self.assertRaises(Review): normalize(root(n))
        source = root(node()); source['fields'] = {'visibleConditions': {'purchaseGoods': 7}}
        with binding(source['children'][0]), self.assertRaisesRegex(Review, 'source_changed'): normalize(source)

    def test_malformed_duplicate_and_over_budget_markup_is_rejected(self):
        for html in ('<div><p>Keep</div>', '<p style="color:red" style="color:blue">Keep</p>',
                     '<p>' + 'x' * 200001 + '</p>'):
            n = node(html)
            with self.subTest(length=len(html)), binding(n), self.assertRaises(Review): normalize(root(n))

    def test_account_and_root_guards(self):
        with patch.object(subject, 'ACCOUNT', 'mv-centr'), self.assertRaisesRegex(Review, 'account_mismatch'):
            normalize(root(node()))
        for source in (None, [], {'name': 'section', 'children': []}, {'name': 'page', 'children': None}):
            with self.subTest(source=source), self.assertRaisesRegex(Review, 'source_invalid'): normalize(source)
        for identity in ((True, 101), (0, 101), ('067', 101), (2**31, 101), (67, None)):
            with self.subTest(identity=identity), self.assertRaisesRegex(Review, 'source_invalid'):
                normalize(root(node()), identity)

    def test_strange_field_and_attribute_types_return_fixed_review_codes(self):
        n = node(); n['fields'] = None
        with patch.object(subject, 'BINDINGS', {(67, 101): ((0,), subject._digest(n), '0' * 64)}), self.assertRaisesRegex(Review, 'source_invalid'):
            normalize(root(n))
        for html in ('<p><img src="https://example.org/image.jpg" style></p>',
                     '<p><a href="https://[invalid">Keep link</a></p>'):
            n = node(html)
            with self.subTest(html=html), binding(n), self.assertRaises(Review): normalize(root(n))
        n = node()
        with binding(n), self.assertRaisesRegex(Review, 'validator_invalid'):
            subject.normalize_reviewed_getcourse(root(n), 67, 101, lambda value: value)


if __name__ == '__main__': unittest.main()

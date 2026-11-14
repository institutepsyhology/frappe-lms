import copy
import json
import unittest
from contextlib import ExitStack
from unittest.mock import patch

from importer import Review
from normalize_editor_nodes import _core
from normalize_source import normalize_payload, static_validator
import normalize_reviewed_intro_lesson as subject


def text(html):
    return {'name': 'text', 'fields': {'anchor': '', 'html': html},
            'style': {'lists': {'text': {'paddingTop': {'value': {'number': 20, 'units': 'px'}}}}}}


def header(label, number):
    result = text(f'<p><a name="{number}"></a></p><h2>{label}</h2>')
    result['name'] = 'header'
    result['fields']['format'] = 'h1'
    return result


def button(label, url):
    return {'name': 'button', 'fields': {'anchor': '', 'blank': True, 'event': '',
            'html': label, 'icon': '', 'linkType': 'url', 'toAnchor': '', 'url': url}}


BUY = [f'<li><a href="https://example.org/buy/{i}">Paid {i}</a></li>' for i in (2, 4, 8)]
CALL = '<p>Pay using the button below.</p>'
MIXED = ('<div id="xdget7"><p>Keep support overview.</p><ul>' + ''.join(BUY) + '</ul>'
         '<p><a href="https://example.org/reference?a=1&amp;b=2" target="_blank">Keep notes</a></p>'
         + CALL + '</div>')


def fixture():
    return {'name': 'page', 'children': [
        {'name': 'section', 'children': [
            {'name': 'column', 'children': [button('Schedule', '#2')]},
            {'name': 'column', 'children': [button('Certificates', '#3')]}]},
        text('<h2><a href="#4">Navigation</a></h2>'),
        header('Schedule', 2),
        text('<p>Keep certificate deadlines and <a href="https://example.org/calculator">Calculator</a>.</p>'),
        header('Certificate requirements', 3),
        text('<p>Keep all assignment and certificate requirements.</p>'),
        header('Support descriptions', 4),
        text(MIXED),
        button('Pay for supervision', 'https://example.org/pay'),
        text('<p>Keep reference information about supervision.</p>'),
        button('Reference document', 'https://example.org/document'),
        text('<p>Keep the closing wishes.</p>'),
        header('Study rules', 5),
        text('<p><a href="https://example.org/rules">Keep study rules</a></p>'),
        {**header('Questionnaire', 6), 'fields': {'html': '<h2>Questionnaire</h2>',
            'format': 'h1', 'anchor': 'survey', 'visibleConditions': {'original': True}}},
        text('<p>Questionnaire only: <a href="https://example.org/survey">Survey</a></p>'),
    ]}


def expected(source):
    result = copy.deepcopy(source)
    for i in subject.ANCHORS:
        html = result['children'][i]['fields']['html']
        start = html.index('<a ')
        end = html.index('</a>') + len('</a>')
        result['children'][i]['fields']['html'] = html[:start] + html[end:]
    html = result['children'][7]['fields']['html']
    for fragment in BUY + [CALL]:
        html = html.replace(fragment, '', 1)
    result['children'][7]['fields']['html'] = html.replace(' id="xdget7"', '')
    for i, node in enumerate(result['children']):
        if i not in subject.OMIT_ROOTS:
            node['fields'].pop('anchor', None)
    result['children'] = [node for i, node in enumerate(result['children']) if i not in subject.OMIT_ROOTS]
    return result


def bindings(source):
    stack = ExitStack()
    stack.enter_context(patch.object(subject, 'SOURCE_APE_SHA256', subject._digest(source)))
    stack.enter_context(patch.object(subject, 'NODE_SHA256',
        {i: subject._digest(node) for i, node in enumerate(source['children'])}))
    stack.enter_context(patch.object(subject, 'RESULT_APE_SHA256', subject._digest(expected(source))))
    anchors = {}
    for i in subject.ANCHORS:
        html = source['children'][i]['fields']['html']
        fragment = html[html.index('<a '):html.index('</a>') + len('</a>')]
        anchors[i] = (1, subject._sha(fragment))
    stack.enter_context(patch.object(subject, 'ANCHORS', anchors))
    stack.enter_context(patch.object(subject, 'PAYMENT_FRAGMENTS', tuple(
        (ordinal, tag, subject._sha(fragment), reason) for ordinal, tag, fragment, reason in (
            (3, 'li', BUY[0], 'session_purchase'), (5, 'li', BUY[1], 'session_purchase'),
            (7, 'li', BUY[2], 'session_purchase'), (11, 'p', CALL, 'payment_call_to_action')))))
    return stack


def normalize(source, cid=207, lid=1975):
    return subject.normalize_reviewed_intro_lesson(source, cid, lid, static_validator())


class ReviewedIntroTests(unittest.TestCase):
    def test_only_authorized_navigation_payment_and_survey_are_removed(self):
        source = fixture()
        before = copy.deepcopy(source)
        with bindings(source):
            result, changes = normalize(source)
            self.assertEqual(result, expected(source))
            self.assertEqual(normalize(source), (result, changes))
        self.assertEqual(source, before)
        serialized = json.dumps(result)
        for value in ('Calculator', 'Keep all assignment and certificate requirements.',
                      'Keep support overview.', 'Keep notes', 'Keep study rules',
                      'Keep reference information about supervision.', 'Reference document'):
            self.assertIn(value, serialized)
        for value in ('Questionnaire', 'Pay using', 'Paid 2', 'Paid 4', 'Paid 8', 'example.org/pay'):
            self.assertNotIn(value, serialized)
        self.assertEqual(len(result['children']), 11)
        reference = [n for n in result['children'] if n['name'] == 'button']
        self.assertEqual(len(reference), 1)
        self.assertEqual(reference[0]['fields']['url'], 'https://example.org/document')
        self.assertFalse(any('anchor' in n['fields'] for n in result['children']))

    def test_owner_omissions_have_path_hash_reason_and_no_private_content(self):
        source = fixture()
        with bindings(source):
            _, changes = normalize(source)
        omitted = [c for c in changes if c['action'] == 'node_omitted']
        self.assertEqual([c['path'] for c in omitted], [[0], [1], [8], [14], [15]])
        self.assertEqual([c['reason'] for c in omitted],
                         ['internal_navigation', 'internal_navigation', 'payment_action', 'questionnaire', 'questionnaire'])
        fragments = [c for c in changes if c['action'] == 'html_fragment_omitted']
        self.assertEqual(len(fragments), 4)
        self.assertEqual([c['reason'] for c in fragments].count('session_purchase'), 3)
        self.assertEqual(len([c for c in changes if c['action'] == 'named_anchor_removed']), 4)
        self.assertTrue(changes[0]['other_support_description_preserved'])
        for token in ('https://', 'Keep support overview', 'Questionnaire'):
            self.assertNotIn(token, json.dumps(changes))

    def test_existing_strict_pipeline_produces_a_ready_plan_and_keeps_reference_button(self):
        source = fixture()
        payload = {'account': 'mastervision', 'source_origin': 'https://shop.mastervision.su',
            'course_id': 207, 'lesson_id': 1975, 'course_title': 'Synthetic',
            'lesson_title': 'Synthetic', 'format': 'ape', 'ape': source}
        before = copy.deepcopy(payload)
        with bindings(source):
            prepared, codes = normalize_payload(payload)
            plan = _core().plan_import(prepared)
            self.assertTrue(plan['ready'], plan['issues'])
            self.assertEqual(prepared['source_original_ape'], source)
            self.assertEqual(prepared['source_normalization']['version'], 22)
            self.assertEqual(normalize_payload(prepared), (prepared, codes))
        self.assertEqual(payload, before)

    def test_every_text_link_condition_and_style_change_invalidates_whole_source(self):
        source = fixture()
        variants = []
        for index, field, value in ((3, 'html', '<p>New teaching instructions.</p>'),
                                    (10, 'url', 'https://example.org/replacement'),
                                    (14, 'visibleConditions', {'changed': True}),
                                    (12, 'anchor', 'different-target')):
            changed = copy.deepcopy(source)
            changed['children'][index]['fields'][field] = value
            variants.append(changed)
        changed = copy.deepcopy(source)
        changed['children'][7]['style']['caption'] = 'New authored material'
        variants.append(changed)
        changed = copy.deepcopy(source)
        changed['fields'] = {'visibleConditions': {'paid': True}}
        variants.append(changed)
        changed = copy.deepcopy(source)
        changed['children'].reverse()
        variants.append(changed)
        with bindings(source):
            for changed in variants:
                with self.subTest(changed=changed), self.assertRaisesRegex(Review, 'source_changed'):
                    normalize(changed)

    def test_changed_node_fragment_or_result_binding_refuses_instead_of_guessing(self):
        source = fixture()
        with bindings(source):
            with patch.dict(subject.NODE_SHA256, {7: '0' * 64}), self.assertRaisesRegex(Review, 'source_changed'):
                normalize(source)
            wrong = list(subject.PAYMENT_FRAGMENTS)
            ordinal, tag, _, reason = wrong[0]
            wrong[0] = (ordinal, tag, '0' * 64, reason)
            with patch.object(subject, 'PAYMENT_FRAGMENTS', tuple(wrong)), self.assertRaisesRegex(Review, 'source_changed'):
                normalize(source)
            with patch.object(subject, 'RESULT_APE_SHA256', '0' * 64), self.assertRaisesRegex(Review, 'material_mismatch'):
                normalize(source)

    def test_presentation_cleaner_cannot_silently_drop_other_material(self):
        source = fixture()
        real_clean = subject.clean_reviewed_html
        def changed_clean(html, validate):
            cleaned, stats, images = real_clean(html, validate)
            return cleaned.replace('Keep support overview.', ''), stats, images
        with bindings(source), patch.object(subject, 'clean_reviewed_html', changed_clean):
            with self.assertRaisesRegex(Review, 'material_mismatch'):
                normalize(source)

    def test_unknown_css_and_authored_ids_stay_for_review_even_with_rebound_source(self):
        for html in ('<p style="display:none">Keep hidden teaching text.</p>',
                     '<p style="transform:rotate(9deg)">Keep teaching text.</p>',
                     '<p><span id="authored-target">Keep teaching text.</span></p>'):
            source = fixture()
            source['children'][3]['fields']['html'] = html
            with bindings(source), self.subTest(html=html), self.assertRaises(Review):
                normalize(source)

    def test_retained_conditions_caption_or_unrecognized_fields_cannot_be_discarded(self):
        for where, key, value in (('fields', 'visibleConditions', {'paid': True}),
                                  ('fields', 'unknown', 'Keep field material'),
                                  ('style', 'caption', 'Keep caption')):
            source = fixture()
            source['children'][3].setdefault(where, {})[key] = value
            with bindings(source), self.subTest(key=key), self.assertRaises(Review):
                normalize(source)

    def test_visible_anchor_body_or_extra_named_target_is_not_removed(self):
        for html in ('<p><a name="2">Keep anchor text</a></p><h2>Schedule</h2>',
                     '<p><a name="2" href="https://example.org/material"></a></p><h2>Schedule</h2>'):
            source = fixture()
            source['children'][2]['fields']['html'] = html
            with bindings(source), self.subTest(html=html), self.assertRaisesRegex(Review, 'source_changed'):
                normalize(source)

    def test_other_sources_are_unchanged_and_account_identity_is_enforced(self):
        source = fixture()
        for identity in ((208, 1975), (207, 1976)):
            result, changes = normalize(source, *identity)
            self.assertEqual((result, changes), (source, []))
            self.assertIsNot(result, source)
        for identity in ((True, 1975), (207, False), (0, 1975)):
            with self.assertRaisesRegex(Review, 'source_invalid'):
                normalize(source, *identity)
        with patch.object(subject, 'ACCOUNT', 'mvcentr'), self.assertRaisesRegex(Review, 'account_mismatch'):
            normalize(source)

    def test_actual_bindings_have_no_source_urls_or_source_html(self):
        self.assertEqual(len(subject.NODE_SHA256), 16)
        self.assertEqual(len(subject.PAYMENT_FRAGMENTS), 4)
        self.assertEqual(len(subject.ANCHORS), 4)
        values = [subject.SOURCE_APE_SHA256, subject.RESULT_APE_SHA256,
                  *subject.NODE_SHA256.values(), *[v[1] for v in subject.ANCHORS.values()],
                  *[v[2] for v in subject.PAYMENT_FRAGMENTS]]
        self.assertTrue(all(len(v) == 64 and not set(v) - set('0123456789abcdef') for v in values))


if __name__ == '__main__':
    unittest.main()

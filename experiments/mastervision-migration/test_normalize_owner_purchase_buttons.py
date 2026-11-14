import copy
import unittest
from unittest.mock import patch

from importer import Review
import normalize_owner_purchase_buttons as subject


def page():
    button = {'id': 'obsolete', 'name': 'button', 'fields': {
        'html': 'Old checkout', 'linkType': 'url', 'url': '{goods_ordering_123}'}, 'children': []}
    return {'name': 'page', 'children': [
        {'name': 'text', 'fields': {'html': '<p>Keep lesson text</p>'}},
        {'name': 'section', 'children': [{'name': 'column', 'children': [button, {
            'name': 'button', 'fields': {'url': 'https://example.org/material', 'html': 'Material'}}]}]},
        {'name': 'video', 'fields': {'videoProvider': 'youtube', 'videoSrc': 'https://youtu.be/ABCDEFGHIJK'}},
        copy.deepcopy(button)]}


def bindings(source):
    return {(529, 5478): (subject._sha(source), (
        ((1, 0, 0), subject._sha(source['children'][1]['children'][0]['children'][0])),
        ((3,), subject._sha(source['children'][3]))))}


class PurchaseOmissionTests(unittest.TestCase):
    def test_only_approved_buttons_omitted_nested_order_material_and_input_preserved(self):
        source = page(); before = copy.deepcopy(source)
        with patch.object(subject, 'APPROVED', bindings(source)):
            result, changes = subject.normalize_owner_purchase_buttons(source, 529, 5478)
        expected = copy.deepcopy(source)
        del expected['children'][3]; del expected['children'][1]['children'][0]['children'][0]
        self.assertEqual(result, expected); self.assertEqual(source, before)
        self.assertEqual([c['path'] for c in changes], [[1, 0, 0], [3]])
        self.assertTrue(all(c['code'] == subject.CODE for c in changes))

    def test_scoped_to_exact_course_and_lesson(self):
        source = page()
        with patch.object(subject, 'APPROVED', bindings(source)):
            for cid, lid in ((529, 5497), (530, 5478)):
                self.assertEqual(subject.normalize_owner_purchase_buttons(source, cid, lid), (source, []))
            self.assertEqual(len(subject.normalize_owner_purchase_buttons(source, '529', '5478')[1]), 2)

    def test_changed_link_label_style_conditions_and_neighbour_rejected(self):
        source = page()
        with patch.object(subject, 'APPROVED', bindings(source)):
            for key, value in (('url', 'https://example.org/new'), ('html', 'Changed'),
                               ('visibleConditions', {'visible': False})):
                changed = copy.deepcopy(source); changed['children'][3]['fields'][key] = value
                with self.assertRaisesRegex(Review, '^owner_purchase_source_changed$'):
                    subject.normalize_owner_purchase_buttons(changed, 529, 5478)
            for changed in (dict(source, caption='Authored'), dict(source, style={'opacity': 0})):
                with self.assertRaisesRegex(Review, '^owner_purchase_source_changed$'):
                    subject.normalize_owner_purchase_buttons(changed, 529, 5478)

    def test_hash_match_alone_cannot_approve_non_purchase_node(self):
        for field, value in (('url', 'https://example.org/pay'), ('linkType', 'anchor')):
            source = page(); source['children'][3]['fields'][field] = value
            with patch.object(subject, 'APPROVED', bindings(source)):
                with self.assertRaisesRegex(Review, '^owner_purchase_source_invalid$'):
                    subject.normalize_owner_purchase_buttons(source, 529, 5478)

    def test_bad_identity_account_structure_and_number_fail(self):
        for cid, lid in ((True, 5478), (529, False), ('0529', 5478), (0, 5478)):
            with self.assertRaisesRegex(Review, '^owner_purchase_source_invalid$'):
                subject.normalize_owner_purchase_buttons(page(), cid, lid)
        with patch.object(subject, 'ACCOUNT', 'mv-centr'):
            with self.assertRaisesRegex(Review, '^owner_purchase_account_mismatch$'):
                subject.normalize_owner_purchase_buttons(page(), 529, 5478)
        for source in ([], {}, {'name': 'page', 'children': 'invalid'}):
            with self.assertRaisesRegex(Review, '^owner_purchase_source_invalid$'):
                subject.normalize_owner_purchase_buttons(source, 529, 5478)

    def test_production_policy_exact_seven_lessons_eight_buttons(self):
        self.assertEqual(set(subject.APPROVED), {(529, 5478), (529, 5498), (529, 5499),
            (558, 5955), (562, 5977), (562, 5981), (562, 5982)})
        self.assertEqual(sum(len(value[1]) for value in subject.APPROVED.values()), 8)


if __name__ == '__main__': unittest.main()

import copy
import hashlib
import unittest
from unittest.mock import patch

import normalize_remaining_static_material as subject
from importer import Review
from normalize_source import static_validator


def page(markup, kind='text', **fields):
    return {'name': 'page', 'fields': {}, 'children': [
        {'id': 'kept-id', 'name': kind, 'fields': {'anchor': '', 'html': markup, **fields}, 'style': {}},
        {'name': 'text', 'fields': {'html': '<p>Unchanged sibling</p>'}}]}


class RemainingStaticTests(unittest.TestCase):
    def apply(self, markup, action='table', kind='text', ape=None, binding=(316, 2261), **fields):
        source = page(markup, kind, **fields) if ape is None else ape
        spec = ((0,), hashlib.sha256(markup.encode()).hexdigest(), kind, action)
        with patch.object(subject, 'APPROVED', {binding: (spec,)}):
            return subject.normalize_remaining_static_material(source, *binding, static_validator())

    def test_alignment_preserves_table_cells_material_and_source(self):
        markup = '<h2><a href="https://example.org/file" target="_blank">Material</a></h2><table border="0"><tr><td align="right">Alpha</td><td>Beta</td></tr></table>'
        original = page(markup); saved = copy.deepcopy(original)
        result, changes = self.apply(markup, ape=original)
        self.assertEqual(original, saved)
        self.assertEqual(result['children'][1], original['children'][1])
        self.assertEqual(result['children'][0]['id'], 'kept-id')
        self.assertTrue(changes)
        static_validator()(result['children'][0]['fields']['html'])
        self.assertEqual(subject._signature(markup), subject._signature(result['children'][0]['fields']['html']))

    def test_middle_alignment_is_only_known_table_binding(self):
        markup = '<table><tr><td valign="middle">Keep</td></tr></table>'
        result, _ = self.apply(markup, binding=(316, 5146))
        self.assertIn('Keep', result['children'][0]['fields']['html'])
        with self.assertRaises(Review): self.apply(markup)

    def test_header_cells_and_ordered_lists_are_preserved(self):
        markup = '<table><thead><tr><th scope="col">Topic</th></tr></thead><tbody><tr><td><ol start="3"><li>Keep one</li><li>Keep two</li></ol></td></tr></tbody></table>'
        result, _ = self.apply(markup, binding=(538, 5603))
        output = result['children'][0]['fields']['html']
        self.assertIn('<strong>Topic</strong>', output)
        self.assertIn('<ol start="3">', output)
        self.assertEqual(subject._signature(markup), subject._signature(output))

    def test_explicit_bullets_and_decimal_markers_survive_table_cleaning(self):
        markup = '<table><tr><td><ul style="list-style-type:disc"><li>Alpha</li></ul><ol start="3" style="list-style-type:decimal"><li>Beta</li></ol></td></tr></table>'
        result, _ = self.apply(markup, binding=(538, 5603))
        output = result['children'][0]['fields']['html']
        self.assertIn('list-style-type:disc', output)
        self.assertIn('list-style-type:decimal', output)
        self.assertIn('start="3"', output)
        self.assertEqual(subject._signature(markup), subject._signature(output))

    def test_only_typed_google_sheets_formatting_runs_are_removed(self):
        markup = '<table><tr><td data-sheets-textstyleruns="{&quot;1&quot;:0}\uee10{&quot;1&quot;:3,&quot;2&quot;:{&quot;5&quot;:1}}">Alpha</td></tr></table>'
        result, _ = self.apply(markup, binding=(656, 7789))
        self.assertEqual(result['children'][0]['fields']['html'], '<table><tr><td>Alpha</td></tr></table>')
        for changed in (markup.replace('{&quot;1&quot;:0}', '{&quot;1&quot;:&quot;Authored text&quot;}'),
                        markup.replace('&quot;5&quot;:1', '&quot;5&quot;:true')):
            with self.subTest(changed=changed), self.assertRaises(Review): self.apply(changed, binding=(656, 7789))

    def test_merged_cells_and_unknown_attributes_are_not_flattened(self):
        for markup in ('<table><tr><td colspan="2">Keep</td></tr></table>',
                       '<table><tr><td rowspan="2">Keep</td></tr></table>',
                       '<table><tr><td data-secret="Keep">Alpha</td></tr></table>',
                       '<table><tr><td align="justify">Keep</td></tr></table>'):
            with self.subTest(markup=markup), self.assertRaises(Review): self.apply(markup)

    def test_approved_merge_keeps_exact_grid_and_ignores_only_known_clipboard_css(self):
        markup = subject._CLIPBOARD + '<table><tr><td colspan="2" rowspan="1">Keep merged</td></tr><tr><td>Alpha</td><td>Beta</td></tr></table>'
        result, _ = self.apply(markup, binding=(656, 7784))
        output = result['children'][0]['fields']['html']
        self.assertIn('<td colspan="2" rowspan="1">Keep merged</td>', output)
        self.assertEqual(output.count('<tr>'), 2)
        self.assertEqual(subject._signature(markup), subject._signature(output))
        for changed in (markup.replace('colspan="2"', 'colspan="17"'),
                        markup.replace('rowspan="1"', 'rowspan="0"'),
                        markup.replace('border: 1px', 'border: 2px')):
            with self.subTest(changed=changed), self.assertRaises(Review): self.apply(changed, binding=(656, 7784))

    def test_safe_header_keeps_exact_markup_lists_and_settings(self):
        markup = '<p><strong>Topic</strong></p><ul><li>First</li><li>Second</li></ul>'
        result, changes = self.apply(markup, action='header', kind='header', format='h4')
        node = result['children'][0]
        self.assertEqual(node['name'], 'text')
        self.assertEqual(node['fields'], {'anchor': '', 'html': markup})
        self.assertEqual(changes[0]['code'], subject.HEADER_CODE)

    def test_simple_header_preserves_level_and_line_break(self):
        markup = 'Practice<br>Topic'
        result, _ = self.apply(markup, action='simple_header', kind='header-simple', level='h2')
        self.assertEqual(result['children'][0]['fields']['html'], '<h2>' + markup + '</h2>')

    def test_empty_simple_header_is_empty_text_with_same_node_position(self):
        result, _ = self.apply('', action='empty_header', kind='header-simple', level='h2')
        self.assertEqual(len(result['children']), 2)
        self.assertEqual(result['children'][0]['fields']['html'], '')
        self.assertEqual(result['children'][0]['name'], 'text')

    def test_exact_code_changes_only_kind_and_preserves_iframe_bytes(self):
        markup = '<p><iframe src="https://drive.google.com/file/d/EXAMPLE_ID/preview" width="640" height="480"></iframe></p>'
        source = page(markup, 'code'); expected = copy.deepcopy(source)
        expected['children'][0]['name'] = 'text'
        result, changes = self.apply(markup, action='code_as_text', kind='code', ape=source)
        self.assertEqual(result, expected)
        self.assertEqual(changes[0]['code'], subject.KIND_CODE)
        for changed in (page(markup + ' changed', 'code'), page(markup, 'text'),
                        page(markup, 'code', visibleConditions={})):
            self.assertEqual(self.apply(markup, action='code_as_text', kind='code', ape=changed), (changed, []))

    def test_source_hash_path_type_and_context_guard(self):
        markup = '<p>Keep</p>'; source = page(markup)
        spec = ((0,), '0' * 64, 'text', 'table')
        with patch.object(subject, 'APPROVED', {(316, 2261): (spec,)}):
            self.assertEqual(subject.normalize_remaining_static_material(source, 316, 2261, static_validator()), (source, []))
        for course, lesson in ((True, 2261), ('0316', 2261), (317, 2261), (316, 0)):
            self.assertEqual(subject.normalize_remaining_static_material(source, course, lesson, static_validator()), (source, []))

    def test_unknown_fields_anchors_children_and_active_styles_are_preserved(self):
        markup = '<table><tr><td align="right">Keep</td></tr></table>'
        for target, field, value in (('node', 'anchor', 'meaningful'), ('node', 'visibleConditions', {}),
                                     ('node', 'displayDelay', 0), ('root', 'displayDelay', 0),
                                     ('root', 'visibleConditions', {})):
            source = page(markup); node = source if target == 'root' else source['children'][0]
            node['fields'][field] = value
            self.assertEqual(self.apply(markup, ape=source), (source, []))
        source = page(markup); source['children'][0]['children'] = [{'name': 'text', 'fields': {'html': 'Keep'}}]
        self.assertEqual(self.apply(markup, ape=source), (source, []))
        source = page(markup); source['children'][0]['style'] = {'caption': 'Keep'}
        self.assertEqual(self.apply(markup, ape=source), (source, []))

    def test_material_loss_is_detected(self):
        markup = '<table><tr><td align="right">Alpha</td></tr></table>'
        with patch.object(subject, '_clean', return_value=('<table><tr><td>Missing</td></tr></table>', {})):
            with self.assertRaisesRegex(Review, 'remaining_static_material_mismatch'): self.apply(markup)

    def test_active_html_hidden_content_and_comments_are_refused(self):
        for markup in ('<table onclick="run()"><tr><td>Keep</td></tr></table>',
                       '<div style="display:none">Hidden</div><table><tr><td>Keep</td></tr></table>',
                       '<table><tr><td>Keep</td></tr></table><!-- unknown -->'):
            with self.subTest(markup=markup), self.assertRaises(Review): self.apply(markup)

    def test_second_application_is_unchanged(self):
        markup = '<table><tr><td align="right">Keep</td></tr></table>'
        spec = ((0,), hashlib.sha256(markup.encode()).hexdigest(), 'text', 'table')
        with patch.object(subject, 'APPROVED', {(316, 2261): (spec,)}):
            result, _ = subject.normalize_remaining_static_material(page(markup), 316, 2261, static_validator())
            self.assertEqual(subject.normalize_remaining_static_material(result, 316, 2261, static_validator()), (result, []))


if __name__ == '__main__': unittest.main()

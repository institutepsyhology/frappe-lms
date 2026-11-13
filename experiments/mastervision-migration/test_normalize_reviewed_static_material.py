import copy
import hashlib
import unittest
from unittest.mock import patch

import normalize_reviewed_static_material as subject
import normalize_source
from importer import Review


def page(html):
    return {'name': 'page', 'fields': {}, 'children': [
        {'id': 'reviewed', 'name': 'text', 'fields': {'html': html, 'anchor': ''}, 'style': {}},
        {'id': 'keep', 'name': 'text', 'fields': {'html': '<p>Unchanged sibling</p>'}}]}


def footer_html():
    return ('<table class="waffle"><thead><tr><th></th><th></th><th></th></tr></thead>'
            '<tbody><tr><th></th><td>Alpha</td><td>Beta</td></tr>' +
            ''.join('<tr><th><div class="row-header-wrapper"></div></th><td colspan="2">' +
                    value + '</td></tr>' for value in (
                        '<strong>Footer one</strong>', '<a href="https://example.org/file">Footer two</a>',
                        'Footer three', 'Footer four')) + '</tbody></table><p>After table</p>')


class ReviewedStaticTests(unittest.TestCase):
    def apply(self, html, binding=(206, 1202), ape=None):
        source = page(html) if ape is None else ape
        approved = {binding: ((0,), hashlib.sha256(html.encode()).hexdigest())}
        with patch.object(subject, 'APPROVED', approved):
            return subject.normalize_reviewed_static_material(source, *binding, normalize_source.static_validator())

    def test_table_preserves_cells_links_and_source(self):
        html = ('<div class="lite-page"><table cellpadding="2" cellspacing="0">'
                '<tbody><tr><td style="padding:2px">Alpha &amp; Beta</td>'
                '<td><a href="https://example.org/file" target="_blank">Document</a></td></tr>'
                '</tbody></table></div>')
        raw = page(html); saved = copy.deepcopy(raw)
        result, changes = self.apply(html, ape=raw)
        self.assertEqual(raw, saved)
        self.assertEqual(result['children'][1], raw['children'][1])
        self.assertEqual(subject._signature(html), subject._signature(result['children'][0]['fields']['html']))
        self.assertEqual(changes[0]['code'], subject.CODE)
        normalize_source.static_validator()(result['children'][0]['fields']['html'])

    def test_google_drive_iframe_is_unchanged(self):
        frame = '<iframe src="https://drive.google.com/file/d/EXAMPLE_ID/preview" width="640" height="480"></iframe>'
        html = '<div class="lite-page">' + frame + '<table><tr><td>Data</td></tr></table></div>'
        result, _ = self.apply(html)
        self.assertIn(frame, result['children'][0]['fields']['html'])

    def test_only_exact_bound_hash_and_path(self):
        html = '<div class="lite-page">Alpha</div>'; source = page(html)
        with patch.object(subject, 'APPROVED', {(206, 1202): ((1,), hashlib.sha256(html.encode()).hexdigest())}):
            self.assertEqual(subject.normalize_reviewed_static_material(source, 206, 1202, normalize_source.static_validator()), (source, []))
        with patch.object(subject, 'APPROVED', {(206, 1202): ((0,), '0' * 64)}):
            self.assertEqual(subject.normalize_reviewed_static_material(source, 206, 1202, normalize_source.static_validator()), (source, []))

    def test_wrong_source_scope_and_noncanonical_identifiers(self):
        source = page('<p>Alpha</p>')
        for course, lesson in [(205, 1202), (206, 9999), (True, 1202), ('0206', 1202)]:
            with self.subTest(course=course, lesson=lesson):
                self.assertEqual(subject.normalize_reviewed_static_material(source, course, lesson, normalize_source.static_validator()), (source, []))

    def test_numeric_string_context_is_supported(self):
        html = '<div class="lite-page">Alpha</div>'
        with patch.object(subject, 'APPROVED', {(206, 1202): ((0,), hashlib.sha256(html.encode()).hexdigest())}):
            result, changes = subject.normalize_reviewed_static_material(page(html), '206', '1202', normalize_source.static_validator())
        self.assertTrue(changes); self.assertNotIn('lite-page', result['children'][0]['fields']['html'])

    def test_existing_page_font_metadata_is_preserved(self):
        html = '<div class="lite-page">Alpha</div>'; source = page(html)
        source['fields'] = {key: 'Unchanged font setting' for key in subject.PAGE_VISUAL_FIELDS}
        source['fields']['backgroundOverlayColor'] = {'r': 255, 'g': 255, 'b': 255}
        result, changes = self.apply(html, ape=source)
        self.assertTrue(changes); self.assertEqual(result['fields'], source['fields'])

    def test_protected_fields_and_ancestors_are_unchanged(self):
        html = '<div class="lite-page">Alpha</div>'
        for target, key, value in [('child', 'anchor', 'important'), ('child', 'visibleConditions', None),
                                   ('child', 'event', 'purchase'), ('root', 'visibleConditions', {}),
                                   ('root', 'displayDelay', 0), ('root', 'event', 'purchase'),
                                   ('root', 'anchor', 'important')]:
            source = page(html); node = source if target == 'root' else source['children'][0]
            node['fields'][key] = value
            with self.subTest(key=key, target=target): self.assertEqual(self.apply(html, ape=source), (source, []))

    def test_caption_style_and_children_are_protected(self):
        html = '<div class="lite-page">Alpha</div>'
        for extra in [{'children': [{'name': 'text', 'fields': {'html': 'Keep'}}]}, {'caption': 'Keep'}, {'style': {'html': 'Keep'}}]:
            source = page(html); source['children'][0].update(extra)
            self.assertEqual(self.apply(html, ape=source), (source, []))

    def test_known_widgets_are_retained_as_empty_divs(self):
        html = '<div class="answers-list"><div class="other-answers"></div></div><div class="talks-widget-button"></div><p>Alpha</p>'
        result, _ = self.apply(html)
        output = result['children'][0]['fields']['html']
        self.assertEqual(output, '<div><div></div></div><div></div><p>Alpha</p>')

    def test_nonempty_widget_or_hidden_material_is_refused(self):
        for html in ['<div class="answers-list">Authored answer</div>',
                     '<div class="talks-widget"><a href="https://example.org">File</a></div>',
                     '<div style="display:none">Hidden text</div>']:
            with self.subTest(html=html):
                with self.assertRaises(Review): self.apply(html)

    def test_verified_empty_widget_identifier_is_retained(self):
        html = '<div class="talks-widget activated-talks-widget" id="w123"></div>'
        result, _ = self.apply(html)
        self.assertEqual(result['children'][0]['fields']['html'], '<div id="w123"></div>')
        with self.assertRaises(Review): self.apply(html.replace('w123', 'purchase'))

    def test_unknown_class_active_html_and_comments_are_refused(self):
        for html in ['<div class="purchase-condition">Keep</div>', '<p onclick="action()">Keep</p>',
                     '<script>alert(1)</script>', '<p>Keep</p><!-- unknown -->']:
            with self.subTest(html=html):
                with self.assertRaises(Review): self.apply(html)

    def test_footer_preserves_exact_inner_html_order_and_main_grid(self):
        html = footer_html(); result, changes = self.apply(html, (206, 1205))
        output = result['children'][0]['fields']['html']
        self.assertEqual(subject._signature(html)[0], subject._signature(output)[0])
        self.assertEqual(output.count('<tr>'), 2)
        self.assertNotIn('colspan', output)
        self.assertIn('</table><div><strong>Footer one</strong></div><div><a href="https://example.org/file">Footer two</a></div>', output)
        self.assertTrue(output.endswith('<div>Footer four</div><p>After table</p>'))
        self.assertEqual(changes[-1], {'path': [0], 'code': subject.FOOTER_CODE, 'rows': 4})
        normalize_source.static_validator()(output)

    def test_footer_changed_grid_is_refused(self):
        html = footer_html()
        cases = [html.replace('colspan="2"', 'colspan="3"', 1),
                 html.replace('<th><div', '<th>Important<div', 1),
                 html.replace('<td>Alpha</td>', '<td rowspan="2">Alpha</td>'),
                 html.replace('Footer four</td>', 'Footer four</td><td>Extra</td>')]
        for source in cases:
            with self.subTest(source=source):
                with self.assertRaises(Review): self.apply(source, (206, 1205))

    def test_footer_empty_sheet_headers_keep_visible_text_boundaries(self):
        html = footer_html().replace('<th><div', '<th>&nbsp;\n<div')
        result, _ = self.apply(html, (206, 1205))
        output = result['children'][0]['fields']['html']
        self.assertEqual(subject._signature(html)[0], subject._signature(output)[0])
        self.assertIn('Footer one Footer two Footer three Footer four', subject._signature(output)[0])

    def test_unapproved_merged_cells_are_never_dropped(self):
        with self.assertRaises(Review): self.apply('<table><tr><td colspan="2">Keep merged</td></tr></table>')

    def test_excel_metadata_only_exact_value_is_removed(self):
        html = '<div align="center" x:publishsource="Excel"><table><tr><td class="xl6429282">Alpha</td></tr></table></div>'
        result, _ = self.apply(html, (206, 1215))
        self.assertNotIn('publishsource', result['children'][0]['fields']['html'])
        with self.assertRaises(Review): self.apply(html.replace('Excel', 'Unknown'), (206, 1215))

    def test_only_nan_width_of_reviewed_lesson_is_removed(self):
        html = '<table width="NaN" style="table-layout:fixed"><tr><td width="NaN">Alpha</td></tr></table>'
        result, _ = self.apply(html, (206, 3101))
        self.assertEqual(result['children'][0]['fields']['html'], '<table><tr><td>Alpha</td></tr></table>')
        with self.assertRaises(Review): self.apply(html)

    def test_only_inert_button_is_a_span(self):
        html = '<p><button type="button">Keep caption</button></p>'
        result, _ = self.apply(html, (206, 1688))
        self.assertEqual(result['children'][0]['fields']['html'], '<p><span>Keep caption</span></p>')
        with self.assertRaises(Review): self.apply(html.replace('type="button"', 'type="submit"'), (206, 1688))

    def test_code_preserves_all_html_and_monospace(self):
        html = '<p><strong>Heading</strong><br><code>Alpha &amp; beta</code></p><ul><li>Keep</li></ul>'
        result, _ = self.apply(html, (259, 1568))
        output = result['children'][0]['fields']['html']
        self.assertEqual(output, html.replace('<code>', '<span style="font-family:monospace">').replace('</code>', '</span>'))
        self.assertEqual(subject._signature(html), subject._signature(output))
        with self.assertRaises(Review): self.apply(html.replace('<code>', '<code class="unknown">'), (259, 1568))

    def test_table_cell_and_material_loss_are_detected_independently(self):
        html = '<table><tr><td>Alpha</td><td>Beta</td></tr></table>'
        original = normalize_source.TablePresentation.handle_data
        def broken(parser, value): original(parser, value.replace('Alpha', 'Missing'))
        with patch.object(normalize_source.TablePresentation, 'handle_data', broken):
            with self.assertRaisesRegex(Review, 'reviewed_static_material_mismatch'): self.apply(html)

    def test_list_numbering_css_cannot_be_silently_removed(self):
        html = '<ol start="3" style="list-style-type:decimal"><li>Alpha</li><li>Beta</li></ol>'
        with self.assertRaisesRegex(Review, 'reviewed_static_material_mismatch'): self.apply(html)

    def test_result_is_idempotent_without_reapplying_source_hash(self):
        html = '<div class="lite-page"><p>Alpha</p></div>'
        with patch.object(subject, 'APPROVED', {(206, 1202): ((0,), hashlib.sha256(html.encode()).hexdigest())}):
            result, _ = subject.normalize_reviewed_static_material(page(html), 206, 1202, normalize_source.static_validator())
            self.assertEqual(subject.normalize_reviewed_static_material(result, 206, 1202, normalize_source.static_validator()), (result, []))

    def test_v16_full_normalizer_keeps_original_footer_and_audio_receipts(self):
        from test_normalize_audio import audio, key, receipt
        from lms.lms.avo_transform import plan_import
        html = footer_html()
        source = {'account': 'mastervision', 'source_origin': 'https://shop.mastervision.su',
                  'course_id': 206, 'lesson_id': 1205, 'course_title': 'Synthetic course',
                  'lesson_title': 'Synthetic lesson', 'format': 'ape', 'ape': page(html)}
        source['ape']['children'].append(audio())
        before = copy.deepcopy(source)
        approved = {(206, 1205): ((0,), hashlib.sha256(html.encode()).hexdigest())}
        with patch.object(subject, 'APPROVED', approved):
            result, codes = normalize_source.normalize_payload(source, {key(): receipt()})
            self.assertEqual(source, before)
            self.assertEqual(result['source_original_ape'], before['ape'])
            self.assertEqual(result['source_normalization']['version'], 16)
            self.assertEqual(result['source_normalization']['audio_assets'], {key(): receipt()})
            self.assertEqual([c['code'] for c in result['source_normalization']['reviewed_material_blocks']],
                             [subject.CODE, subject.FOOTER_CODE])
            self.assertTrue(plan_import(result)['ready'])
            self.assertEqual(normalize_source.normalize_payload(result), (result, codes))
            self.assertEqual(normalize_source.normalize_payload(result, {key(): receipt()}), (result, codes))
        self.assertEqual({k: v for k, v in result.items() if k not in {'ape', 'source_original_ape', 'source_normalization'}},
                         {k: v for k, v in source.items() if k != 'ape'})

    def test_v16_replay_rejects_changed_original_witness(self):
        html = '<p><code>Exact original</code></p>'
        source = {'account': 'mastervision', 'source_origin': 'https://shop.mastervision.su',
                  'course_id': 259, 'lesson_id': 1568, 'course_title': 'Synthetic course',
                  'lesson_title': 'Synthetic lesson', 'format': 'ape', 'ape': page(html)}
        approved = {(259, 1568): ((0,), hashlib.sha256(html.encode()).hexdigest())}
        with patch.object(subject, 'APPROVED', approved):
            result, codes = normalize_source.normalize_payload(source)
            self.assertEqual(result['source_normalization']['version'], 16)
            self.assertEqual(normalize_source.normalize_payload(result), (result, codes))
            result['source_original_ape']['children'][0]['fields']['html'] += '<p>Changed</p>'
            with self.assertRaisesRegex(Review, 'normalization_metadata_conflict'):
                normalize_source.normalize_payload(result)


if __name__ == '__main__': unittest.main()

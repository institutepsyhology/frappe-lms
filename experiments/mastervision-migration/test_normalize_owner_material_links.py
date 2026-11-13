"""Synthetic exact-link omissions preserve timing, audio, text and other anchors."""
import copy
import hashlib
import unittest
from unittest.mock import patch

from importer import Review
import normalize_owner_material_links as mod

VIMEO = 'https://vimeo.com/123456789'
ANCHOR = '<a href="' + VIMEO + '" target="_blank"><strong>Old video caption</strong></a>'
SOURCE = ('<p>Before ' + ANCHOR + ' after.</p><pre>TIMING 00:10\nKeep this line</pre>'
          '<p><a href="https://example.test/audio-one">Audio 1</a> and <em>other instructions</em>.</p>')
CLEANED = SOURCE.replace(ANCHOR, '', 1)
def sha(value): return hashlib.sha256(value.encode()).hexdigest()
def text(value): return {'id': 'source-text', 'name': 'text', 'fields': {'anchor': '', 'html': value}, 'style': {}}
def page(source=SOURCE): return {'name': 'page', 'children': [text('<p>First</p>'), text('<p>Second</p>'), text(source), text('<p>Last</p>')]}
def policy(source=SOURCE, outer=ANCHOR, url=VIMEO):
    return {'path': (2,), 'html_sha256': sha(source), 'url_sha256': sha(url), 'outer_sha256': sha(outer)}


class OwnerMaterialLinkTests(unittest.TestCase):
    def setUp(self):
        rules = {key: policy() for key in mod.APPROVED}
        self.rules = patch.object(mod, 'APPROVED', rules); self.rules.start(); self.addCleanup(self.rules.stop)

    def test_four_scopes_remove_only_exact_anchor_including_nested_caption(self):
        for course, lesson in ((326, 2636), (329, 2729), (374, 3162), (376, 3165)):
            source = page(); before = copy.deepcopy(source)
            out, changes = mod.normalize_owner_material_links(source, course, lesson)
            expected = page(CLEANED)
            self.assertEqual(source, before); self.assertEqual(out, expected)
            self.assertEqual(changes, [{'path': [2], 'code': mod.CODE, 'html_sha256': sha(SOURCE),
                'url_sha256': sha(VIMEO), 'outer_sha256': sha(ANCHOR)}])

    def test_all_remaining_html_is_byte_exact_and_timing_audio_caption_survive(self):
        out, _ = mod.normalize_owner_material_links(page(), 326, 2636)
        remaining = out['children'][2]['fields']['html']
        self.assertEqual(remaining, CLEANED)
        for value in ('TIMING 00:10\nKeep this line', 'Audio 1', 'https://example.test/audio-one', 'other instructions'):
            self.assertIn(value, remaining)
        self.assertNotIn('Old video caption', remaining)

    def test_wrong_lesson_course_account_and_identity_type_stay_untouched(self):
        for course, lesson in ((326, 2637), (325, 2636), (329, 2636), ('326', 2636), (326, '2636'), (True, 2636)):
            original = page(); self.assertEqual(mod.normalize_owner_material_links(original, course, lesson), (original, []))
        with patch.object(mod, 'ACCOUNT', 'mv-centr'):
            with self.assertRaisesRegex(Review, '^owner_material_account_mismatch$'):
                mod.normalize_owner_material_links(page(), 326, 2636)

    def test_changed_surrounding_caption_html_and_missing_target_are_not_authorized(self):
        for source in (SOURCE.replace('Before', 'Changed caption'), SOURCE.replace(ANCHOR, ''), SOURCE + '<p>New material</p>'):
            ape = page(source); self.assertEqual(mod.normalize_owner_material_links(ape, 326, 2636), (ape, []))

    def test_url_outer_and_full_html_hashes_are_independent_guards(self):
        for key in ('html_sha256', 'url_sha256', 'outer_sha256'):
            rules = {scope: policy() for scope in mod.APPROVED}; rules[(326, 2636)][key] = '0' * 64
            with patch.object(mod, 'APPROVED', rules):
                source = page(); self.assertEqual(mod.normalize_owner_material_links(source, 326, 2636), (source, []))

    def test_duplicate_or_second_vimeo_anchor_is_never_selected(self):
        for extra in (ANCHOR, '<a href="https://vimeo.com/987654321" target="_blank">Another</a>'):
            source = SOURCE + extra; rules = {scope: policy(source) for scope in mod.APPROVED}
            with patch.object(mod, 'APPROVED', rules):
                ape = page(source); self.assertEqual(mod.normalize_owner_material_links(ape, 326, 2636), (ape, []))

    def test_same_link_in_other_original_path_remains(self):
        source = page(); source['children'][1], source['children'][2] = source['children'][2], source['children'][1]
        self.assertEqual(mod.normalize_owner_material_links(source, 326, 2636), (source, []))
        wrong={scope:policy() for scope in mod.APPROVED};wrong[(326,2636)]['path']=(1,)
        with patch.object(mod,'APPROVED',wrong):
            source=page();self.assertEqual(mod.normalize_owner_material_links(source,326,2636),(source,[]))

    def test_visibility_conditions_anchors_styles_children_and_unknown_fields_protect(self):
        cases=[]
        for key, value in (('anchor', 'important'), ('visibleConditions', []), ('displayDelay', 0), ('caption', 'Keep caption')):
            source = page(); source['children'][2]['fields'][key] = value; cases.append(source)
        source = page(); source['fields'] = {'visibleConditions': [{'purchase': 'required'}]}; cases.append(source)
        source = page(); source['children'][2]['style'] = {'caption': 'Keep style caption'}; cases.append(source)
        source = page(); source['children'][2]['children'] = [text('<p>Child</p>')]; cases.append(source)
        source = page(); source['children'][2]['unknown'] = None; cases.append(source)
        for source in cases:self.assertEqual(mod.normalize_owner_material_links(source, 326, 2636), (source, []))

    def test_active_unknown_label_or_parent_markup_is_not_authorized(self):
        for outer in (ANCHOR.replace('<strong>', '<strong onclick="act()">'),
                      ANCHOR.replace('<strong>Old video caption</strong>', '<img src="https://example.test/caption.png">'),
                      ANCHOR.replace('<strong>Old video caption</strong>', '<script>act()</script>')):
            source = SOURCE.replace(ANCHOR, outer); rules={scope:policy(source,outer) for scope in mod.APPROVED}
            with patch.object(mod, 'APPROVED', rules):
                ape=page(source);self.assertEqual(mod.normalize_owner_material_links(ape,326,2636),(ape,[]))
        source=SOURCE.replace(ANCHOR,'<span data-condition="purchase">'+ANCHOR+'</span>')
        with patch.object(mod,'APPROVED',{scope:policy(source) for scope in mod.APPROVED}):
            ape=page(source);self.assertEqual(mod.normalize_owner_material_links(ape,326,2636),(ape,[]))

    def test_extra_material_loss_is_caught_by_independent_expected_signature(self):
        remove=mod._remove_outer
        for before,after in (('TIMING 00:10','Lost timing'),('https://example.test/audio-one','https://example.test/other-audio')):
            def broken(source,start,end):return remove(source,start,end).replace(before,after)
            with patch.object(mod,'_remove_outer',broken):
                with self.assertRaisesRegex(Review,'^owner_material_signature_mismatch$'):
                    mod.normalize_owner_material_links(page(),326,2636)

    def test_second_pass_is_identical_and_scope_is_only_the_four_owner_bindings(self):
        out,_=mod.normalize_owner_material_links(page(),326,2636)
        again,changes=mod.normalize_owner_material_links(out,326,2636);self.assertEqual((again,changes),(out,[]))
        self.assertEqual(set(mod.APPROVED),{(326,2636),(329,2729),(374,3162),(376,3165)})

    def test_invalid_tree_has_a_fixed_diagnostic(self):
        for source in (None,[],{'name':'text'},{'name':'page','children':['bad']},{'name':'page','children':[{'name':'text','fields':[]}]}):
            with self.assertRaisesRegex(Review,'^owner_material_source_invalid$'):
                mod.normalize_owner_material_links(source,326,2636)


if __name__ == '__main__': unittest.main()

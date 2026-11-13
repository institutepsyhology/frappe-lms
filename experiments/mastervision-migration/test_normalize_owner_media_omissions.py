"""Scoped owner decisions never remove a neighbouring educational image or link."""
import copy
import hashlib
import unittest
from unittest.mock import patch

from importer import Review
import normalize_owner_media_omissions as mod

GIF = 'https://example.test/approved-animation.gif'
MISSING = 'https://example.test/approved-missing.png'
PNG = 'https://example.test/keep-educational-diagram.png'
TAG = '<img width="240" height="180" src="' + MISSING + '">'
HTML = '<p>Keep instructions ' + TAG + ' and caption.</p><p><a href="https://example.test/notes">Notes</a><img src="' + PNG + '"></p>'
def sha(value): return hashlib.sha256(value.encode()).hexdigest()
def text(value): return {'id': 'text', 'name': 'text', 'fields': {'anchor': '', 'html': value}}
def image(url=GIF, **fields):
    return {'id': 'image', 'name': 'image', 'fields': {'anchor': '', 'displayDelay': None,
        'imageSrc': url, 'linkHref': '', 'visibleConditions': None, **fields}, 'style': {}}
def section(node): return {'name': 'section', 'children': [{'name': 'column', 'children': [node]}]}
def gif_page(node=None):
    return {'name': 'page', 'children': [section(image() if node is None else node), section(image('https://example.test/avatar.png')),
                                       text('<p>Text</p>'), text('<p>More</p>'), text('<p><img src="' + PNG + '"></p>')]}
def missing_page(value=HTML): return {'name': 'page', 'children': [text('<p>First</p>'), text('<p>Second</p>'), text(value)]}


class OwnerMediaTests(unittest.TestCase):
    def setUp(self):
        policies = copy.deepcopy(mod.APPROVED)
        for policy in policies.values():
            policy['src_sha256'] = sha(GIF) if policy['kind'] == 'animated_gif' else sha(MISSING)
            if 'tag_sha256' in policy: policy['tag_sha256'] = sha(TAG)
        self.policy = patch.object(mod, 'APPROVED', policies)
        self.policy.start(); self.addCleanup(self.policy.stop)

    def test_four_exact_gif_bindings_remove_only_original_leaf(self):
        for lesson in (6825, 6848, 6849, 6852):
            source = gif_page(); before = copy.deepcopy(source)
            out, changes = mod.normalize_owner_media_omissions(source, 618, lesson)
            expected = copy.deepcopy(source); expected['children'][0]['children'][0]['children'] = []
            self.assertEqual(source, before); self.assertEqual(out, expected)
            self.assertEqual(changes, [{'path': [0, 0, 0], 'code': mod.CODE, 'kind': 'animated_gif', 'src_sha256': sha(GIF)}])

    def test_inline_404_removes_exact_tag_and_keeps_every_other_byte(self):
        source = missing_page(); before = copy.deepcopy(source)
        out, changes = mod.normalize_owner_media_omissions(source, 520, 5223)
        expected = copy.deepcopy(source); expected['children'][2]['fields']['html'] = HTML.replace(TAG, '', 1)
        self.assertEqual(source, before); self.assertEqual(out, expected)
        self.assertEqual(changes, [{'path': [2], 'code': mod.CODE, 'kind': 'missing_404_image',
            'src_sha256': sha(MISSING), 'tag_sha256': sha(TAG)}])

    def test_matching_media_in_other_courses_lessons_or_account_is_not_omitted(self):
        for course, lesson in ((617, 6825), (618, 6826), (520, 5224), ('618', 6825), (618, '6825'), (True, 6825)):
            source = gif_page(); self.assertEqual(mod.normalize_owner_media_omissions(source, course, lesson), (source, []))
        with patch.object(mod, 'ACCOUNT', 'mv-centr'):
            with self.assertRaisesRegex(Review, '^owner_media_account_mismatch$'):
                mod.normalize_owner_media_omissions(gif_page(), 618, 6825)

    def test_same_gif_at_a_different_original_path_stays(self):
        source = gif_page(); source['children'][0]['children'][0]['children'].insert(0, image(PNG))
        self.assertEqual(mod.normalize_owner_media_omissions(source, 618, 6825), (source, []))

    def test_changed_native_source_or_neighboring_png_is_never_omitted(self):
        for url in (PNG, GIF + '?changed=1'):
            source = gif_page(image(url)); self.assertEqual(mod.normalize_owner_media_omissions(source, 618, 6825), (source, []))

    def test_native_captions_links_actions_children_and_unknown_fields_are_protected(self):
        for fields in ({'html': 'Educational caption'}, {'caption': 'Caption'}, {'linkHref': 'https://example.test/file'},
                       {'anchor': 'section'}, {'event': 'download'}, {'unknown': None}, {'visibleConditions': []},
                       {'displayDelay': 0}):
            source = gif_page(image(**fields)); self.assertEqual(mod.normalize_owner_media_omissions(source, 618, 6825), (source, []))
        node = image(); node['children'] = [text('<p>Keep child material</p>')]
        source = gif_page(node); self.assertEqual(mod.normalize_owner_media_omissions(source, 618, 6825), (source, []))

    def test_parent_purchase_conditions_and_native_style_content_are_protected(self):
        conditional = gif_page(); conditional['children'][0]['fields'] = {'visibleConditions': [{'purchase': 'required'}]}
        unknown = gif_page(); unknown['children'][0]['visibleConditions'] = []
        for source in (conditional, unknown):
            self.assertEqual(mod.normalize_owner_media_omissions(source, 618, 6825), (source, []))
        node = image(); node['style'] = {'caption': 'Keep style content'}
        source = gif_page(node); self.assertEqual(mod.normalize_owner_media_omissions(source, 618, 6825), (source, []))

    def test_duplicate_gif_is_a_changed_capture_not_a_second_approved_omission(self):
        source = gif_page(); source['children'][0]['children'][0]['children'].append(image())
        self.assertEqual(mod.normalize_owner_media_omissions(source, 618, 6825), (source, []))

    def test_inline_image_wrapped_in_a_link_or_action_is_protected(self):
        for wrapped in ('<a href="https://example.test/material">' + TAG + '</a>', '<button>' + TAG + '</button>',
                        '<div onclick="act()">' + TAG + '</div>', '<div data-condition="purchase">' + TAG + '</div>'):
            source = missing_page('<p>' + wrapped + '</p>')
            self.assertEqual(mod.normalize_owner_media_omissions(source, 520, 5223), (source, []))

    def test_changed_html_tag_caption_or_duplicate_source_is_not_selected(self):
        for source_html in (HTML.replace('width="240"', 'width="241"'), HTML.replace(TAG, TAG.replace('>', ' alt="caption">')),
                            HTML.replace(TAG, TAG + TAG), HTML.replace(TAG, TAG.replace(MISSING, MISSING + '?new=1'))):
            source = missing_page(source_html)
            self.assertEqual(mod.normalize_owner_media_omissions(source, 520, 5223), (source, []))

    def test_inline_parent_ape_anchor_children_and_unknown_settings_stay(self):
        for field in ('anchor', 'visibleConditions'):
            source = missing_page(); source['children'][2]['fields'][field] = 'protected'
            self.assertEqual(mod.normalize_owner_media_omissions(source, 520, 5223), (source, []))
        source = missing_page(); source['children'][2]['children'] = [text('<p>Child</p>')]
        self.assertEqual(mod.normalize_owner_media_omissions(source, 520, 5223), (source, []))

    def test_second_pass_is_idempotent_for_both_kinds(self):
        for source, course, lesson in ((gif_page(), 618, 6825), (missing_page(), 520, 5223)):
            out, _ = mod.normalize_owner_media_omissions(source, course, lesson)
            again, changes = mod.normalize_owner_media_omissions(out, course, lesson)
            self.assertEqual((again, changes), (out, []))

    def test_scope_has_only_five_approved_bindings_and_does_not_include_inline_pngs(self):
        self.assertEqual(set(mod.APPROVED), {(520, 5223), (618, 6825), (618, 6848), (618, 6849), (618, 6852)})
        self.assertTrue(all(p['path'] == (0, 0, 0) for p in mod.APPROVED.values() if p['kind'] == 'animated_gif'))

    def test_invalid_tree_raises_fixed_code_without_partial_result(self):
        for source in (None, [], {'name': 'text'}, {'name': 'page', 'children': ['bad']}, {'name': 'page', 'children': [{'name': 'text', 'fields': []}]}):
            with self.assertRaisesRegex(Review, '^owner_media_ape_invalid$'):
                mod.normalize_owner_media_omissions(source, 618, 6825)


if __name__ == '__main__': unittest.main()

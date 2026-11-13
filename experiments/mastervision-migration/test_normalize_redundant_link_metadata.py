import copy
import unittest
from unittest.mock import patch

from importer import Review
import normalize_redundant_link_metadata as links
from normalize_source import static_validator


def tree(markup):
    return {'name': 'page', 'children': [{'name': 'text', 'fields': {'html': markup}}]}


class RedundantLinkTests(unittest.TestCase):
    def clean(self, markup):
        return links.normalize_redundant_link_metadata(tree(markup), static_validator())

    def test_only_equal_metadata_is_removed_and_material_is_exact(self):
        markup = '<p>Before {name} <a data-cke-saved-href="https://example.test/a?x=1&amp;y=2" target="_blank" href="https://example.test/a?x=1&amp;y=2">Keep <b>label</b></a> after</p>'
        source = tree(markup); saved = copy.deepcopy(source)
        out, changes = links.normalize_redundant_link_metadata(source, static_validator())
        cleaned = out['children'][0]['fields']['html']
        self.assertEqual(source, saved)
        self.assertEqual(links._signature(markup), links._signature(cleaned))
        self.assertNotIn(links.ATTRIBUTE, cleaned)
        self.assertEqual(changes, [{'path': [0], 'code': links.CODE, 'links': 1}])
        self.assertEqual(links.normalize_redundant_link_metadata(out, static_validator()), (out, []))

    def test_multiline_multiple_links_and_charrefs_preserve_order(self):
        markup = '<p>A\n<a href="https://example.test/1" data-cke-saved-href="https://example.test/1">&#65;</a>\n<a data-cke-saved-href="https://example.test/2" href="https://example.test/2">B</a></p>'
        out, changes = self.clean(markup)
        self.assertEqual(changes[0]['links'], 2)
        self.assertEqual(links._signature(markup), links._signature(out['children'][0]['fields']['html']))

    def test_conflicting_empty_missing_and_duplicate_addresses_are_untouched(self):
        for attrs in ('href="https://example.test/a" data-cke-saved-href="https://example.test/b"',
                      'href="" data-cke-saved-href=""',
                      'data-cke-saved-href="https://example.test/a"',
                      'href="https://example.test/a" href="https://example.test/a" data-cke-saved-href="https://example.test/a"'):
            markup = '<p><a ' + attrs + '>Keep</a></p>'
            self.assertEqual(self.clean(markup), (tree(markup), []))

    def test_unsafe_html_actions_and_urls_are_not_accepted(self):
        for markup in ('<a href="javascript:alert(1)" data-cke-saved-href="javascript:alert(1)">Keep</a>',
                       '<a href="https://example.test/1" data-cke-saved-href="https://example.test/1" onclick="go()">Keep</a>',
                       '<script>doSomething()</script><a href="https://example.test/1" data-cke-saved-href="https://example.test/1">Keep</a>'):
            self.assertEqual(self.clean(markup), (tree(markup), []))

    def test_metadata_on_nonlinks_and_text_is_preserved(self):
        for markup in ('<p>data-cke-saved-href</p>', '<span data-cke-saved-href="https://example.test/1">Keep</span>'):
            self.assertEqual(self.clean(markup), (tree(markup), []))

    def test_material_mismatch_is_fatal(self):
        markup = '<a href="https://example.test/1" data-cke-saved-href="https://example.test/1">Keep</a>'
        with patch.object(links, '_signature', side_effect=[['before'], ['after']]):
            with self.assertRaisesRegex(Review, 'redundant_link_material_mismatch'):
                self.clean(markup)


if __name__ == '__main__': unittest.main()

"""Conservative iframe extraction; original APE remains in the private payload."""
import copy
import hashlib
from html.parser import HTMLParser
import json
import unittest

from importer import Review
from lms.lms.avo_transform import plan_import
from normalize_source import normalize_payload


YOUTUBE = "https://www.youtube.com/embed/abcdefghijk"
RUTUBE = "https://rutube.ru/play/embed/0123456789abcdef0123456789abcdef/?p=synthetic_key"


def frame(url=YOUTUBE, extra=""):
    return '<iframe width="560" height="315" src="' + url + '" frameborder="0" allow="accelerometer; autoplay; encrypted-media; gyroscope; picture-in-picture" allowfullscreen' + extra + '></iframe>'


def payload(html=None):
    return {"account": "mastervision", "source_origin": "https://shop.mastervision.su", "course_id": 1,
            "lesson_id": 4, "course_title": "Synthetic", "lesson_title": "Synthetic", "format": "ape",
            "ape": {"name": "page", "children": [{"id": "synthetic", "name": "text", "fields": {"html": '<p>' + frame() + '</p>' if html is None else html}, "children": []}]}}


class NormalizeTests(unittest.TestCase):
    def test_existing_iframe_payload_fingerprint_is_unchanged(self):
        normalized, _ = normalize_payload(payload())
        encoded = json.dumps(normalized, ensure_ascii=True, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()
        self.assertEqual(hashlib.sha256(encoded).hexdigest(), '652e8d763e5ddda04178bf1ddcb4424fbf926f576519b041d5cdaddeb332acbc')

    def test_single_youtube_becomes_native_video_and_preserves_original(self):
        original = payload()
        frozen = copy.deepcopy(original)
        normalized, codes = normalize_payload(original)
        self.assertEqual(original, frozen)
        self.assertEqual(normalized["source_original_ape"], frozen["ape"])
        self.assertEqual(codes, ["embedded_video_iframe_normalized"])
        video = normalized["ape"]["children"][0]
        self.assertEqual(video["name"], "video")
        self.assertEqual(video["id"], "synthetic")
        self.assertEqual(video["fields"], {"videoProvider": "youtube", "videoSrc": YOUTUBE})
        plan = plan_import(normalized)
        self.assertTrue(plan["ready"], plan["issues"])
        self.assertEqual(len(plan["blocks"]), 1)

    def test_no_iframe_leaves_original_content_and_no_extra_metadata(self):
        original = payload("<p>Complete text and {name}</p>")
        normalized, codes = normalize_payload(original)
        self.assertEqual(normalized, original)
        self.assertIsNot(normalized, original)
        self.assertEqual(codes, [])
        self.assertNotIn("source_original_ape", normalized)

    def test_existing_static_drive_iframe_with_text_stays_unchanged(self):
        source = payload('<p>Keep this caption</p><iframe src="https://drive.google.com/file/d/synthetic/preview" width="640" height="480"></iframe>')
        self.assertTrue(plan_import(source)["ready"])
        normalized, codes = normalize_payload(source)
        self.assertEqual(normalized, source)
        self.assertEqual(codes, [])

    def test_rutube_private_key_is_retained(self):
        normalized, _ = normalize_payload(payload(frame(RUTUBE)))
        self.assertEqual(normalized["ape"]["children"][0]["fields"], {"videoProvider": "rutube", "videoSrc": RUTUBE})
        self.assertTrue(plan_import(normalized)["ready"])

    def test_two_adjacent_iframes_remain_two_independent_videos(self):
        original = payload()
        second = copy.deepcopy(original["ape"]["children"][0])
        second["id"], second["fields"]["html"] = "second", frame(RUTUBE)
        original["ape"]["children"].append(second)
        normalized, _ = normalize_payload(original)
        self.assertEqual([v["fields"]["videoProvider"] for v in normalized["ape"]["children"]], ["youtube", "rutube"])
        self.assertTrue(all("videoProvider2" not in n["fields"] for n in normalized["ape"]["children"]))
        plan = plan_import(normalized)
        self.assertTrue(plan["ready"], plan["issues"])
        self.assertEqual(len(plan["blocks"]), 2)

    def test_existing_typed_alternative_pair_is_unchanged(self):
        original = payload()
        original["ape"]["children"][0] = {"name": "video", "fields": {"videoProvider": "youtube", "videoSrc": YOUTUBE, "videoProvider2": "rutube", "videoSrc2": RUTUBE}}
        normalized, codes = normalize_payload(original)
        self.assertEqual(normalized, original)
        self.assertEqual(codes, [])

    def test_idempotence_checks_original_metadata(self):
        once, codes = normalize_payload(payload())
        twice, second_codes = normalize_payload(once)
        self.assertEqual(twice, once)
        self.assertEqual(second_codes, codes)
        once["ape"]["children"][0]["fields"]["videoSrc"] = "https://youtu.be/01234567890"
        with self.assertRaisesRegex(Review, "normalization_metadata_conflict"):
            normalize_payload(once)

    def test_vimeo_is_not_silently_replaced(self):
        original = payload(frame("https://player.vimeo.com/video/123456"))
        frozen = copy.deepcopy(original)
        with self.assertRaisesRegex(Review, "vimeo_video_unavailable"):
            normalize_payload(original)
        self.assertEqual(original, frozen)

    def test_foreign_accounts_and_origins_are_rejected(self):
        for key, value in (("account", "mv-centr"), ("source_origin", "https://shop.mv-centr.ru")):
            source = payload()
            source[key] = value
            with self.subTest(key=key), self.assertRaisesRegex(Review, "normalization_account_mismatch"):
                normalize_payload(source)

    def test_unknown_or_confusable_urls_are_reviewed(self):
        for url in ("https://youtube.com.evil.test/embed/abcdefghijk", "javascript:alert(1)",
                    "//www.youtube.com/embed/abcdefghijk", "https://user@www.youtube.com/embed/abcdefghijk",
                    "https://www.youtube.com:443/embed/abcdefghijk", "https://www.youtube.com/embed/short",
                    YOUTUBE + "#fragment", YOUTUBE + "?origin=https://other.test", YOUTUBE + "?start=1&start=2"):
            with self.subTest(url=url), self.assertRaises(Review):
                normalize_payload(payload(frame(url)))

    def test_text_links_and_multiple_frames_are_not_discarded(self):
        for markup in ("<p>Keep this explanation</p>" + frame(), frame() + "<a href='https://example.test'>File</a>", frame() + frame(), "<p>{name}</p>" + frame()):
            with self.subTest(length=len(markup)), self.assertRaises(Review):
                normalize_payload(payload(markup))

    def test_active_or_unknown_markup_is_not_executed_or_dropped(self):
        for markup in (frame(extra=' onload="alert(1)"'), frame(extra=' sandbox="allow-scripts"'),
                       '<script></script>' + frame(), '<!-- comment -->' + frame(),
                       '<div class="unknown">' + frame() + '</div>', '<p>' + frame(),
                       frame().replace('</iframe>', ''), frame(extra=' src="' + YOUTUBE + '"')):
            with self.subTest(length=len(markup)), self.assertRaises(Review):
                normalize_payload(payload(markup))

    def test_nonempty_anchors_children_and_unknown_fields_are_reviewed(self):
        for mutation in (lambda n: n["fields"].update(anchor="keep-anchor"),
                         lambda n: n["fields"].update(extra="keep-setting"),
                         lambda n: n.update(children=[{"name": "text", "fields": {"html": "Keep child"}}])):
            source = payload()
            mutation(source["ape"]["children"][0])
            with self.assertRaises(Review):
                normalize_payload(source)

    def test_unknown_block_kind_with_iframe_is_reviewed(self):
        source = payload()
        source["ape"]["children"][0]["name"] = "code"
        with self.assertRaises(Review):
            normalize_payload(source)

    def test_editor_repairs_use_v2_and_keep_original_witness(self):
        original = payload('<p>Remaining text</p>')
        original['ape']['children'].insert(0, {'name': 'video', 'fields': {'videoProvider': 'youtube', 'videoSrc': '', 'videoSrc2': ''}})
        normalized, codes = normalize_payload(original)
        self.assertIn('empty_video_block_omitted', codes)
        self.assertEqual(normalized['source_normalization']['version'], 2)
        self.assertEqual(normalized['source_original_ape'], original['ape'])
        self.assertTrue(plan_import(normalized)['ready'])
        self.assertEqual(normalize_payload(normalized), (normalized, codes))


def table_signature(markup):
    class Signature(HTMLParser):
        def __init__(self):
            super().__init__(convert_charrefs=True)
            self.style, self.text, self.hrefs, self.cells, self.active = False, [], [], [], []
        def handle_starttag(self, tag, attrs):
            if tag == 'style':
                self.style = True
            if tag in ('td', 'th'):
                self.cells.append([tag, []])
                self.active.append(len(self.cells) - 1)
            self.hrefs.extend(value for key, value in attrs if key == 'href')
        def handle_endtag(self, tag):
            if tag == 'style':
                self.style = False
            if tag in ('td', 'th') and self.active:
                self.active.pop()
        def handle_data(self, data):
            if not self.style:
                self.text.append(data)
                for index in self.active:
                    self.cells[index][1].append(data)
    parser = Signature()
    parser.feed(markup)
    return ''.join(parser.text), parser.hrefs, [(tag, ''.join(parts)) for tag, parts in parser.cells]


class TablePresentationTests(unittest.TestCase):
    def test_styles_are_removed_without_changing_text_links_spans_or_cells(self):
        markup = '<style type="text/css">td {height: 23px; padding-inline-start: 2px}</style>' \
                 '<p>Keep {name} &amp; every word.</p><table style="height:23px"><tbody><tr>' \
                 '<td style="height:23px"><span style="color:red">First&nbsp;cell</span>' \
                 '<a href="https://example.test/a?k=synthetic&amp;n=1">File</a></td>' \
                 '<td style="height:23px">Second <strong>cell</strong></td></tr></tbody></table>' \
                 '<a href="https://example.test/b">Next</a>'
        original = payload(markup)
        normalized, codes = normalize_payload(original)
        self.assertEqual(codes, ['static_table_presentation_normalized'])
        self.assertEqual(normalized['source_normalization']['version'], 2)
        self.assertEqual(normalized['source_original_ape'], original['ape'])
        cleaned = normalized['ape']['children'][0]['fields']['html']
        self.assertNotIn('<style', cleaned)
        self.assertNotIn(' style=', cleaned)
        self.assertIn('<span>', cleaned)
        self.assertEqual(table_signature(cleaned), table_signature(markup))
        self.assertTrue(plan_import(normalized)['ready'])
        self.assertEqual(normalize_payload(normalized), (normalized, codes))

    def test_already_accepted_table_stays_byte_identical(self):
        source = payload('<table><tbody><tr><td>First</td><td><span>Second</span></td></tr></tbody></table>')
        normalized, codes = normalize_payload(source)
        self.assertEqual(normalized, source)
        self.assertEqual(codes, [])

    def test_tableless_markup_does_not_get_presentation_cleanup(self):
        source = payload('<p style="height:23px">Keep original</p>')
        self.assertEqual(normalize_payload(source), (source, []))

    def test_mixed_new_table_and_existing_iframe_use_v2_without_pairing(self):
        source = payload()
        source['ape']['children'].append({'name': 'text', 'fields': {'html': '<table style="height:23px"><tr><td>Cell</td></tr></table>'}})
        normalized, codes = normalize_payload(source)
        self.assertEqual(codes, ['embedded_video_iframe_normalized', 'static_table_presentation_normalized'])
        self.assertEqual(normalized['source_normalization']['version'], 2)
        self.assertEqual(normalize_payload(normalized), (normalized, codes))
        self.assertTrue(plan_import(normalized)['ready'])

    def test_active_markup_or_resources_are_never_stripped_into_ready_content(self):
        cases = [
            '<script>alert(1)</script>', '<form></form>', '<img src="https://example.test/a.png">',
            '<iframe src="https://example.test/"></iframe>', '<link rel="stylesheet" href="https://example.test/a.css">',
            '<p onclick="alert(1)">Text</p>', '<style>@import "https://example.test/a.css";</style>',
            '<style>p::after{content:"Keep generated material"}</style>',
        ]
        for extra in cases:
            source = payload(extra + '<table style="height:23px"><tr><td>Cell</td></tr></table>')
            with self.subTest(extra=extra), self.assertRaises(Review):
                normalize_payload(source)
        for style in ['background:url(https://example.test/a.png)', 'width:expression(alert(1))', r'background:u\72l(a)', 'background:image-set("a.png" 1x)']:
            source = payload('<table style="height:23px;' + style.replace('"', '&quot;') + '"><tr><td>Cell</td></tr></table>')
            with self.subTest(style=style), self.assertRaises(Review):
                normalize_payload(source)

    def test_unknown_tags_attributes_and_spans_remain_review_cases(self):
        for table in ['<table unknown="keep" style="height:23px"><tr><td>Cell</td></tr></table>',
                      '<table style="height:23px"><tfoot><tr><td>Footer</td></tr></tfoot></table>',
                      '<table style="height:23px"><tr><td colspan="2">Merged</td></tr></table>']:
            with self.subTest(table=table), self.assertRaises(Review):
                normalize_payload(payload(table))

    def test_confirmed_spreadsheet_metadata_and_header_presentation_are_normalized(self):
        markup = '<table xmlns="http://www.w3.org/1999/xhtml" border="1" cellpadding="0" cellspacing="0" width="500">' \
                 '<colgroup width="500"><col width="250"></colgroup><thead><tr height="20">' \
                 '<th width="250">First header</th><th>Second header</th></tr></thead><tbody><tr>' \
                 '<td data-sheets-value="{&quot;1&quot;:2,&quot;2&quot;:&quot;Data&quot;}" data-sheets-numberformat="{}" width="250" height="20">' \
                 '<span>Keep data</span><a href="https://example.test/material">Material</a></td><td>Second cell</td></tr></tbody></table>'
        original = payload(markup)
        normalized, codes = normalize_payload(original)
        cleaned = normalized['ape']['children'][0]['fields']['html']
        self.assertEqual(codes, ['static_table_presentation_normalized'])
        self.assertEqual(normalized['source_original_ape'], original['ape'])
        self.assertIn('<td><strong>First header</strong></td>', cleaned)
        self.assertIn('<td><strong>Second header</strong></td>', cleaned)
        self.assertIn('<span>Keep data</span>', cleaned)
        self.assertEqual(table_signature(cleaned)[:2], table_signature(markup)[:2])
        self.assertEqual([text for _, text in table_signature(cleaned)[2]], [text for _, text in table_signature(markup)[2]])
        self.assertTrue(plan_import(normalized)['ready'])

    def test_existing_approved_iframe_is_preserved_verbatim_next_to_table(self):
        iframe = '<iframe height="480" src="https://drive.google.com/file/d/synthetic/preview" width="640"></iframe>'
        normalized, _ = normalize_payload(payload(iframe + '<table style="height:23px"><tr><td>Cell</td></tr></table>'))
        cleaned = normalized['ape']['children'][0]['fields']['html']
        self.assertIn(iframe, cleaned)
        self.assertTrue(plan_import(normalized)['ready'])

    def test_unbalanced_markup_and_duplicate_attributes_are_not_repaired(self):
        for table in ['<table style="height:23px"><tr><td>Cell</table>',
                      '<table style="height:23px" style="height:24px"><tr><td>Cell</td></tr></table>']:
            with self.subTest(table=table), self.assertRaises(Review):
                normalize_payload(payload(table))


if __name__ == "__main__":
    unittest.main()

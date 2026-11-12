"""Conservative iframe extraction; original APE remains in the private payload."""
import copy
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


if __name__ == "__main__":
    unittest.main()

import unittest
from lms.lms.avo_transform import plan_import


def sample(content, fmt="preview"):
    result = {"account": "mv-centr", "course_id": 5, "lesson_id": 13,
              "course_title": "Курс", "lesson_title": "Урок", "format": fmt}
    result["content" if fmt == "preview" else "ape"] = content
    return result


class TransformTests(unittest.TestCase):
    def test_pair_text_links_and_original_query(self):
        youtube = "https://youtu.be/abcdefghijk"
        rutube = "https://rutube.ru/video/private/0123456789abcdef0123456789abcdef/?p=secret&x=1"
        payload = sample([
            {"type": "video_pair", "players": [{"provider": "youtube", "url": youtube},
                                              {"provider": "rutube", "url": rutube}]},
            {"type": "text", "text": "Здравствуйте, {name}\nследующая строка"},
            {"type": "links", "items": [{"label": "План & текст", "url": "https://example.test/a?p=1&x=2"}]},
        ])
        plan = plan_import(payload)
        self.assertTrue(plan["ready"])
        self.assertIn("video_player_may_drop_parameters", plan["warnings"])
        self.assertEqual(plan["blocks"][0]["data"]["rutube"], rutube)
        self.assertEqual(plan["blocks"][0]["data"]["youtube"], youtube)
        self.assertIn("{name}<br>", plan["blocks"][1]["data"]["text"])
        self.assertIn("&amp;", plan["blocks"][2]["data"]["text"])

    def test_unknown_missing_and_same_provider_refuse(self):
        for item in [
            {"type": "video_pair", "players": []},
            {"type": "video_pair", "players": [{"provider": "youtube", "url": "https://youtu.be/abc"},
                                              {"provider": "youtube", "url": "https://youtu.be/def"}]},
            {"type": "text", "html": '<iframe src="https://example.test/"></iframe>'},
            {"type": "unknown"},
        ]:
            self.assertFalse(plan_import(sample([item]))["ready"])

    def test_ape_traversal_and_html(self):
        root = {"name": "page", "fields": {}, "children": [
            {"name": "text", "fields": {"html": '<p>Привет, {name}! <a href="https://example.test/?x=1&amp;y=2">Материал</a></p>'}},
            {"name": "video", "fields": {"videoProvider": "youtube", "videoSrc": "https://youtu.be/abcdefghijk",
             "videoProvider2": "rutube", "videoSrc2": "https://rutube.ru/video/private/0123456789abcdef0123456789abcdef/?p=1"}}]}
        out = plan_import(sample(root, "ape"))
        self.assertTrue(out["ready"])
        self.assertEqual([x["type"] for x in out["blocks"]], ["paragraph", "videoChoice"])
        self.assertIn("{name}", out["blocks"][0]["data"]["text"])

    def test_image_requires_prepared_private_file(self):
        src = sample([{"type": "image", "image_key": "slide1", "caption": "Схема"}])
        self.assertIn("image_not_prepared", plan_import(src)["issues"])
        self.assertFalse(plan_import(src, {"slide1": "/private/files/../bad.png"})["ready"])
        plan = plan_import(src, {"slide1": "/private/files/import-123.png"})
        self.assertTrue(plan["ready"])
        self.assertEqual(plan["blocks"][0]["data"]["url"], "/private/files/import-123.png")

    def test_reject_invalid_values(self):
        x = sample([])
        x["course_id"] = True
        with self.assertRaises(ValueError):
            plan_import(x)

    def test_incomplete_and_order_are_not_silent(self):
        self.assertIn("empty_lesson", plan_import(sample({"name": "page", "children": []}, "ape"))["issues"])
        x = sample([{"type": "text", "text": "second", "order": 2},
                    {"type": "text", "text": "first", "order": 1}])
        self.assertIn("ambiguous_block_order", plan_import(x)["issues"])
        x = sample({"name": "page", "children": [{"name": "text", "fields": {"html": "Text", "other": "lost"}}]}, "ape")
        self.assertIn("unsupported_text_settings", plan_import(x)["issues"])
        x = sample([{"type": "text", "html": '<a href="https://example.test/ bad">x</a>'}])
        self.assertFalse(plan_import(x)["ready"])
        self.assertIn("invalid_block", plan_import(sample([{"type": []}]))["issues"])
        self.assertIn("unknown_preview_fields", plan_import(sample([{"type": "text", "text": "x", "extra": "not rendered"}]))["issues"])
        x = sample([{"type": "text", "html": '<a href="javascript:alert(1)">x</a>'}])
        self.assertFalse(plan_import(x)["ready"])
        x = sample([])
        x["account"] = "other/../account"
        with self.assertRaises(ValueError):
            plan_import(x)


if __name__ == "__main__":
    unittest.main()

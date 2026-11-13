"""Conservative iframe extraction; original APE remains in the private payload."""
import copy
import hashlib
from html.parser import HTMLParser
import json
import unittest
from unittest.mock import patch

from importer import Review
from lms.lms.avo_transform import plan_import
from normalize_source import normalize_payload
from normalize_audio import CODE as AUDIO_CODE


YOUTUBE = "https://www.youtube.com/embed/abcdefghijk"
RUTUBE = "https://rutube.ru/play/embed/0123456789abcdef0123456789abcdef/?p=synthetic_key"


def frame(url=YOUTUBE, extra=""):
    return '<iframe width="560" height="315" src="' + url + '" frameborder="0" allow="accelerometer; autoplay; encrypted-media; gyroscope; picture-in-picture" allowfullscreen' + extra + '></iframe>'


def payload(html=None):
    return {"account": "mastervision", "source_origin": "https://shop.mastervision.su", "course_id": 1,
            "lesson_id": 4, "course_title": "Synthetic", "lesson_title": "Synthetic", "format": "ape",
            "ape": {"name": "page", "children": [{"id": "synthetic", "name": "text", "fields": {"html": '<p>' + frame() + '</p>' if html is None else html}, "children": []}]}}


class NormalizeTests(unittest.TestCase):
    def test_image_editor_label_v9_keeps_the_image_and_replays_with_audio(self):
        from test_normalize_audio import audio,key,receipt
        source=payload('<p>Body</p>')
        image={'name':'image','id':'label-image','fields':{'anchor':'','html':'Изображение',
               'imageSrc':'https://f1.autoweboffice.ru/synthetic/picture.jpg'}}
        source['ape']['children'].extend([image,audio()]);before=copy.deepcopy(source)
        normalized,codes=normalize_payload(source,{key():receipt()})
        self.assertEqual(source,before)
        self.assertEqual(normalized['source_original_ape'],before['ape'])
        self.assertEqual(normalized['source_normalization']['version'],9)
        self.assertIn('image_label_preserved',codes)
        expected=copy.deepcopy(image);del expected['fields']['html']
        self.assertEqual(normalized['ape']['children'][1],expected)
        self.assertTrue(plan_import(normalized,{'label-image':'/private/files/prepared.jpg'})['ready'])
        self.assertEqual(normalize_payload(normalized),(normalized,codes))
        changed=copy.deepcopy(normalized)
        changed['source_normalization']['image_label_blocks'][0]['path']=[0]
        with self.assertRaisesRegex(Review,'normalization_metadata_conflict'):
            normalize_payload(changed)

    def test_image_editor_label_v9_replays_without_audio_and_does_not_consume_other_captions(self):
        source=payload('<p>Body</p>')
        source['ape']['children'].append({'name':'image','id':'label-image','fields':{
            'html':'Изображение','imageSrc':'https://f1.autoweboffice.ru/synthetic/picture.jpg'}})
        normalized,codes=normalize_payload(source)
        self.assertEqual(normalized['source_normalization']['version'],9)
        self.assertEqual(normalize_payload(normalized),(normalized,codes))
        source['ape']['children'][-1]['fields']['html']='A meaningful caption'
        self.assertEqual(normalize_payload(source),(source,[]))

    def approved_image_payload(self):
        source = payload('<p>Keep material</p>')
        source.update(course_id=377,lesson_id=3185)
        image = {'id':'missing-image','name':'image','fields':{'anchor':'',
                 'imageSrc':'https://f1.autoweboffice.ru/synthetic/missing.jpg'}}
        source['ape']['children'] = [{'name':'section','children':[{'name':'container',
                                     'children':[image,*source['ape']['children']]}]}]
        return source

    def test_approved_missing_image_v8_preserves_all_other_content_and_original(self):
        import normalize_approved_images as approved
        source = self.approved_image_payload();before=copy.deepcopy(source)
        key = hashlib.sha256(source['ape']['children'][0]['children'][0]['children'][0]['fields']['imageSrc'].encode()).hexdigest()
        with patch.dict(approved.APPROVED,{(377,3185):key},clear=True):
            normalized,codes=normalize_payload(source)
            self.assertEqual(source,before)
            self.assertEqual(normalized['source_original_ape'],before['ape'])
            self.assertEqual(normalized['ape']['children'][0]['children'][0]['children'],
                             before['ape']['children'][0]['children'][0]['children'][1:])
            self.assertEqual(normalized['source_normalization']['version'],8)
            self.assertIn(approved.CODE,codes)
            self.assertNotIn('audio_assets',normalized['source_normalization'])
            self.assertTrue(plan_import(normalized)['ready'])
            self.assertEqual(normalize_payload(normalized),(normalized,codes))

    def test_approved_missing_image_v8_with_audio_replays_and_rejects_tampering(self):
        import normalize_approved_images as approved
        from test_normalize_audio import audio,key,receipt
        source=self.approved_image_payload()
        source['ape']['children'][0]['children'][0]['children'].append(audio())
        image_key=hashlib.sha256(source['ape']['children'][0]['children'][0]['children'][0]['fields']['imageSrc'].encode()).hexdigest()
        with patch.dict(approved.APPROVED,{(377,3185):image_key},clear=True):
            normalized,codes=normalize_payload(source,{key():receipt()})
            self.assertEqual(normalized['source_normalization']['version'],8)
            self.assertEqual(normalized['source_normalization']['audio_assets'],{key():receipt()})
            self.assertTrue(plan_import(normalized)['ready'])
            self.assertEqual(normalize_payload(normalized),(normalized,codes))
            with self.assertRaisesRegex(Review,'^normalization_metadata_conflict$'):
                normalize_payload(normalized,{key():receipt(size=1)})
            changed=copy.deepcopy(normalized)
            changed['source_normalization']['approved_image_omissions'][0]['url_sha256']='0'*64
            with self.assertRaisesRegex(Review,'^normalization_metadata_conflict$'):
                normalize_payload(changed)

    def test_audio_v7_retains_original_controls_order_and_only_used_receipts(self):
        from test_normalize_audio import audio, key, receipt
        original = payload('<p>Before</p>')
        original['ape']['children'].extend([audio(), {'name':'text','fields':{'html':'After'}}])
        before = copy.deepcopy(original)
        assets = {key():receipt(), 'c'*64:receipt()}
        assets_before = copy.deepcopy(assets)
        normalized, codes = normalize_payload(original, assets)
        self.assertEqual(original, before)
        self.assertEqual(assets, assets_before)
        self.assertEqual(normalized['source_original_ape'], before['ape'])
        self.assertEqual(normalized['ape']['children'][0], original['ape']['children'][0])
        self.assertEqual(normalized['ape']['children'][2], original['ape']['children'][2])
        self.assertEqual(normalized['ape']['children'][1]['id'], original['ape']['children'][1]['id'])
        metadata = normalized['source_normalization']
        self.assertEqual(metadata['version'], 7)
        self.assertEqual(metadata['audio_assets'], {key():receipt()})
        self.assertEqual(metadata['audio_blocks'], [{'path':[1], 'code':AUDIO_CODE, 'url_sha256':key()}])
        self.assertIn(AUDIO_CODE, codes)
        self.assertTrue(plan_import(normalized)['ready'])
        self.assertNotIn('autoweboffice', json.dumps(normalized['ape']))

    def test_audio_v7_reproduces_its_full_fingerprint_without_external_mapping(self):
        from test_normalize_audio import audio, key, receipt
        source = payload('<p>Body</p>'); source['ape']['children'].append(audio())
        normalized, codes = normalize_payload(source, {key():receipt()})
        before = copy.deepcopy(normalized)
        for mapping in (None, {key():receipt()}, {key():receipt(), 'c'*64:receipt()}):
            self.assertEqual(normalize_payload(normalized, mapping), (before, codes))
        self.assertEqual(normalized, before)
        encode = lambda value: json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(',',':')).encode()
        self.assertEqual(hashlib.sha256(encode(normalize_payload(normalized)[0])).digest(),
                         hashlib.sha256(encode(normalized)).digest())

    def test_audio_v7_rejects_changed_missing_or_untrusted_used_receipts(self):
        from test_normalize_audio import audio, key, receipt
        source = payload('<p>Body</p>'); source['ape']['children'].append(audio())
        normalized, _ = normalize_payload(source, {key():receipt()})
        for external in ({}, [], {key():receipt(size=2)}, {key():receipt(file_url='https://other.example/file.mp3')}):
            with self.subTest(external=external), self.assertRaisesRegex(Review, '^normalization_metadata_conflict$'):
                normalize_payload(normalized, external)
        mutations = [lambda m:m.pop('audio_assets'), lambda m:m.update(audio_assets={}),
            lambda m:m['audio_assets'][key()].update(size=True),
            lambda m:m['audio_assets'][key()].update(md5='bad'),
            lambda m:m['audio_assets'][key()].update(file_url='/files/untrusted.mp3'),
            lambda m:m['audio_assets'][key()].update(account='mv-centr'),
            lambda m:m['audio_assets'].update({'c'*64:receipt()}),
            lambda m:m['audio_blocks'][0].update(url_sha256='c'*64)]
        for mutate in mutations:
            changed = copy.deepcopy(normalized); mutate(changed['source_normalization'])
            with self.assertRaisesRegex(Review, '^normalization_metadata_conflict$'):
                normalize_payload(changed)

    def test_fresh_audio_missing_assets_is_a_review_without_mutating_source(self):
        from test_normalize_audio import audio
        source = payload('<p>Body</p>'); source['ape']['children'].append(audio())
        before = copy.deepcopy(source)
        with self.assertRaisesRegex(Review, '^audio_asset_not_prepared$'): normalize_payload(source)
        self.assertEqual(source, before)

    def test_audio_v7_combines_stage_and_other_normalization_with_exact_original_witness(self):
        from test_normalize_audio import audio, key, receipt
        import normalize_stage_widgets as widgets
        from test_normalize_stage_widgets import widget, sha, canonical, EXPECTED_DOM, SCRIPT, CSS
        source = payload(); source['ape']['children'].extend([widget(), audio()])
        with patch.multiple(widgets, DOM_SHA256=sha(canonical(EXPECTED_DOM)), SCRIPT_SHA256=sha(SCRIPT), STYLESHEET_SHA256=sha(CSS)):
            normalized, codes = normalize_payload(source, {key():receipt()})
            self.assertEqual(normalized['source_original_ape'], source['ape'])
            self.assertEqual(normalized['source_normalization']['version'], 7)
            self.assertEqual(len(normalized['source_normalization']['stage_blocks']), 1)
            self.assertEqual(len(normalized['source_normalization']['audio_blocks']), 1)
            self.assertIn('embedded_video_iframe_normalized', codes)
            self.assertIn('static_course_stage_preserved', codes)
            self.assertIn(AUDIO_CODE, codes)
            self.assertEqual(normalize_payload(normalized), (normalized, codes))
            self.assertTrue(plan_import(normalized)['ready'])

    def test_no_audio_keeps_all_six_prior_metadata_fingerprints_even_with_extra_receipts(self):
        from test_normalize_audio import key, receipt
        import normalize_stage_widgets as widgets
        from test_normalize_stage_widgets import widget, sha, canonical, EXPECTED_DOM, SCRIPT, CSS
        fixtures = [payload()]
        source = payload('<p>Body</p>'); source['ape']['children'].insert(0, {'name':'video','fields':{'videoProvider':'youtube','videoSrc':'','videoSrc2':''}}); fixtures.append(source)
        fixtures.append(payload('<p>Before<img alt="" src="https://f1.autoweboffice.ru/synthetic.jpg">After</p>'))
        source = payload('<p>Body</p>'); source['ape']['children'].append({'name':'button','fields':{'linkType':'url','url':'https://example.test/material','html':'<strong>Material</strong>'}}); fixtures.append(source)
        source = payload('<p>Body</p>'); source['ape']['children'] = [{'name':'unfolding','fields':{'initialState':'all-folded','expandedSpeedRate':1,'onlyOneExpanded':True},'children':[{'name':'unfolding-item','fields':{'headerHtml':'Header'},'children':source['ape']['children']}]}]; fixtures.append(source)
        source = payload('<p>Body</p>'); source['ape']['children'].insert(0, widget()); fixtures.append(source)
        expected = ['652e8d763e5ddda04178bf1ddcb4424fbf926f576519b041d5cdaddeb332acbc',
            '681ee12fea9add30f3f84736a1ae8c5e590e6a8cb818d75deed5354840c9a99a',
            '536b26b16623e9d0b12ad6b657e0208b9005b04da9a7a32e51c5fbdb5340cd9e',
            'a61060edfdbea191d0a0c8f82dc5d2142e9cbb001003c1e410a0ba589690a77c',
            '012e2d2da5701afccec7153bde84f8828cd857f8cd36b8c5ee42ec37c7c1629c',
            '2c465d8a906694e0f55b718f6a77aeb24dc91449496bae7103f9dfcc5889d9b6']
        with patch.multiple(widgets, DOM_SHA256=sha(canonical(EXPECTED_DOM)), SCRIPT_SHA256=sha(SCRIPT), STYLESHEET_SHA256=sha(CSS)):
            for version, (source, digest) in enumerate(zip(fixtures, expected), 1):
                normalized, codes = normalize_payload(source, {key():receipt()})
                self.assertEqual(normalized['source_normalization']['version'], version)
                self.assertNotIn('audio_assets', normalized['source_normalization'])
                encoded = json.dumps(normalized, ensure_ascii=True, sort_keys=True, separators=(',',':'), allow_nan=False).encode()
                self.assertEqual(hashlib.sha256(encoded).hexdigest(), digest)
                self.assertEqual(normalize_payload(normalized), (normalized, codes))

    def test_verified_accordion_integration_retains_header_body_and_original(self):
        original = payload('<p>Body</p>')
        body = original['ape']['children']
        original['ape']['children'] = [{'name':'unfolding','id':'accordion','fields':{
            'initialState':'all-folded','expandedSpeedRate':1,'onlyOneExpanded':True},
            'children':[{'name':'unfolding-item','id':'item','fields':{'headerHtml':'<p>Header</p>'},'children':body}]}]
        before = copy.deepcopy(original)
        normalized, codes = normalize_payload(original)
        self.assertEqual(original, before)
        self.assertTrue(plan_import(normalized)['ready'])
        self.assertEqual(normalized['source_original_ape'], before['ape'])
        self.assertEqual(normalized['source_normalization']['version'], 5)
        self.assertIn('accordion_content_flattened', codes)
        contents = normalized['ape']['children'][0]['children'][0]['children']
        self.assertEqual([node['fields']['html'] for node in contents], ['<p>Header</p>','<p>Body</p>'])
        self.assertEqual(normalize_payload(normalized), (normalized, codes))

    def test_verified_stage_integration_is_static_and_retains_original(self):
        from unittest.mock import patch
        import normalize_stage_widgets as widgets
        from test_normalize_stage_widgets import widget, sha, canonical, EXPECTED_DOM, SCRIPT, CSS
        original = payload('<p>Body</p>')
        original['ape']['children'].insert(0, widget())
        with patch.multiple(widgets, DOM_SHA256=sha(canonical(EXPECTED_DOM)),
                            SCRIPT_SHA256=sha(SCRIPT), STYLESHEET_SHA256=sha(CSS)):
            normalized, codes = normalize_payload(original)
            self.assertTrue(plan_import(normalized)['ready'])
            self.assertEqual(normalized['source_original_ape'], original['ape'])
            self.assertEqual(normalized['source_normalization']['version'], 6)
            self.assertIn('static_course_stage_preserved', codes)
            self.assertEqual(normalize_payload(normalized), (normalized, codes))
            self.assertEqual(normalized['ape']['children'][0]['fields']['html'], '<p><strong>Course stage</strong> · 14%</p>')

    def test_formatted_button_integration_retains_original_and_old_plain_payload(self):
        original = payload('<p>Keep text</p>')
        original['ape']['children'].append({'name':'button','id':'material','fields':{
            'linkType':'url','url':'https://example.test/material','html':'<span style="font-size:18px">Material</span>','blank':True}})
        normalized, codes = normalize_payload(original)
        self.assertTrue(plan_import(normalized)['ready'])
        self.assertEqual(normalized['source_original_ape'], original['ape'])
        self.assertIn('button_label_html_preserved', codes)
        self.assertEqual(normalized['source_normalization']['version'], 4)
        self.assertEqual(normalize_payload(normalized), (normalized, codes))
        plain = copy.deepcopy(original)
        plain['ape']['children'][-1]['fields']['html'] = 'Plain<br>material'
        self.assertEqual(normalize_payload(plain), (plain, []))

    def test_legacy_fullscreen_boolean_attributes_do_not_change_rutube_video(self):
        normalized, _ = normalize_payload(payload(frame(RUTUBE, ' webkitallowfullscreen mozallowfullscreen')))
        self.assertEqual(normalized['ape']['children'][0]['fields']['videoSrc'], RUTUBE)
        self.assertTrue(plan_import(normalized)['ready'])
        for attribute in ('webkitallowfullscreen', 'mozallowfullscreen'):
            with self.assertRaises(Review):
                normalize_payload(payload(frame(RUTUBE, ' ' + attribute + '="javascript:bad()"')))

    def test_standalone_code_iframe_uses_the_same_strict_native_player_conversion(self):
        original = payload(frame(RUTUBE))
        original['ape']['children'][0]['name'] = 'code'
        normalized, codes = normalize_payload(original)
        self.assertTrue(plan_import(normalized)['ready'])
        self.assertEqual(normalized['ape']['children'][0]['name'], 'video')
        self.assertEqual(normalized['source_original_ape'], original['ape'])
        self.assertIn('embedded_video_iframe_normalized', codes)

    def test_inline_image_integration_preserves_original_and_repeats_identically(self):
        original = payload('<p>Before<img alt="" src="https://f1.autoweboffice.ru/mastergroup/school/example.jpg">After <a href="https://example.test/">Link</a></p>')
        before = copy.deepcopy(original)
        normalized, codes = normalize_payload(original)
        self.assertEqual(original, before)
        self.assertEqual(normalized['source_original_ape'], before['ape'])
        self.assertEqual(normalized['source_normalization']['version'], 3)
        self.assertIn('inline_html_images_normalized', codes)
        nodes = normalized['ape']['children']
        self.assertEqual([node['name'] for node in nodes], ['text', 'image', 'text'])
        self.assertTrue(plan_import(normalized, {nodes[1]['id']: '/private/files/prepared.jpg'})['ready'])
        self.assertEqual(normalize_payload(normalized), (normalized, codes))

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
        source["ape"]["children"][0]["name"] = "future-block"
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

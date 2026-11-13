"""Synthetic native-player data preserves exact video identity and typed pairs."""
import copy
import json
import unittest

from importer import Review
from normalize_editor_nodes import _core
import normalize_native_video_sources as mod

YT = 'AbCdEfGhI12'
RT_ID = '1234567890abcdef1234567890abcdef'
RT = 'https://rutube.ru/video/private/' + RT_ID + '/?p=Synthetic_key-1'


def video(source=YT, **fields):
    return {'id': 'source-video', 'name': 'video', 'fields': {
        'videoProvider': 'youtube', 'videoSrc': source, 'nativePlayer': False,
        'videoProvider2': 'rutube', 'videoSrc2': RT, 'nativePlayer2': False,
        'anchor': '', 'html': 'Видео', 'posterSrc': '', 'posterSrc2': '',
        'isShowProgressControl': True, 'isShowProgressControl2': True,
        'isShowFastRewindButtons': True, 'isShowFastRewindButtons2': True,
        'embeddedHtml': '', 'isFloating': None, **fields},
        'style': {'spacing': {'margin': '12px'}}, 'children': []}


def page(*children): return {'name': 'page', 'children': list(children)}
def payload(ape):
    return {'account': 'mastervision', 'source_origin': 'https://shop.mastervision.su',
            'course_id': 1, 'lesson_id': 2, 'course_title': 'Synthetic course',
            'lesson_title': 'Synthetic lesson', 'format': 'ape', 'ape': ape}
def validate(value): raise AssertionError('No new HTML may be generated')


class NativeVideoSourceTests(unittest.TestCase):
    def normalize(self, ape): return mod.normalize_native_video_sources(ape, validate)
    def unchanged(self, node):
        ape = page(node); self.assertEqual(self.normalize(ape), (ape, []))

    def test_exact_observed_youtube_forms_preserve_id_and_all_other_fields(self):
        for source, canonical, kind in (
                (YT, 'https://youtu.be/' + YT, 'youtube_bare_id'),
                ('watch?v=' + YT, 'https://www.youtube.com/watch?v=' + YT, 'youtube_relative_watch'),
                ('watch?v=' + YT + '&feature=youtu.be', 'https://www.youtube.com/watch?v=' + YT + '&feature=youtu.be', 'youtube_relative_watch'),
                ('hhttps://youtu.be/' + YT, 'https://youtu.be/' + YT, 'youtube_same_id_scheme')):
            ape = page(video(source)); before = copy.deepcopy(ape)
            out, changes = self.normalize(ape)
            expected = copy.deepcopy(ape); expected['children'][0]['fields']['videoSrc'] = canonical
            self.assertEqual(ape, before); self.assertEqual(out, expected)
            self.assertEqual(mod._youtube_id(source), mod._youtube_id(canonical))
            self.assertEqual(changes, [{'path': [0], 'code': mod.CODE, 'slot': 1, 'kind': kind}])

    def test_rutube_title_prefix_keeps_exact_private_id_query_and_youtube(self):
        source = 'Synthetic module 7.2 — practice ' + RT
        ape = page(video('https://youtu.be/' + YT, videoSrc2=source)); before = copy.deepcopy(ape)
        out, changes = self.normalize(ape)
        expected = copy.deepcopy(ape); expected['children'][0]['fields']['videoSrc2'] = RT
        self.assertEqual(ape, before); self.assertEqual(out, expected)
        self.assertEqual(mod._rutube_id(source), mod._rutube_id(RT))
        self.assertEqual(source.split('?', 1)[1], RT.split('?', 1)[1])
        self.assertEqual(changes, [{'path': [0], 'code': mod.CODE, 'slot': 2, 'kind': 'rutube_same_id_title_prefix'}])

    def test_single_youtube_and_single_prefixed_rutube_are_preserved_as_single(self):
        for node in (video(videoSrc2=''), video('Synthetic material ' + RT, videoProvider='rutube', videoSrc2='', videoProvider2='')):
            out, changes = self.normalize(page(node)); self.assertEqual(len(changes), 1)
            plan = _core().plan_import(payload(out)); self.assertTrue(plan['ready'])
            self.assertEqual(len(plan['blocks']), 1)
            self.assertEqual(sum(bool(plan['blocks'][0]['data'][p]) for p in ('youtube', 'rutube')), 1)

    def test_real_core_invalid_pair_becomes_same_two_sources(self):
        source = payload(page(video('watch?v=' + YT)))
        self.assertEqual(_core().plan_import(source)['issues'], ['video_url_invalid', 'empty_lesson'])
        ape, _ = self.normalize(source['ape']); out = copy.deepcopy(source); out['ape'] = ape
        plan = _core().plan_import(out); self.assertTrue(plan['ready'])
        self.assertEqual(len(plan['blocks']), 1)
        self.assertEqual(plan['blocks'][0]['data'], {'youtube': 'https://www.youtube.com/watch?v=' + YT, 'rutube': RT, 'defaultProvider': 'youtube'})

    def test_every_native_mode_and_unknown_flag_type_stays_unchanged(self):
        for mode in (None, True, 0, 'false', [], {}): self.unchanged(video(nativePlayer=mode))
        self.unchanged(video(isFloating=0))

    def test_uncertain_or_same_provider_second_sources_are_not_repaired(self):
        for fields in ({'videoSrc2': 'not a URL'}, {'videoProvider2': 'youtube', 'videoSrc2': 'https://youtu.be/' + YT},
                       {'videoProvider2': 'rutube', 'videoSrc2': YT}, {'videoProvider2': 'embedded', 'videoSrc2': ''},
                       {'nativePlayer2': True}, {'videoProvider2': 'vimeo'}):
            self.unchanged(video(**fields))

    def test_bad_both_sides_are_not_partially_normalized(self):
        self.unchanged(video(videoSrc2='Synthetic material ' + RT))

    def test_ambiguous_and_nonobserved_youtube_strings_are_never_guessed(self):
        for source in (YT[:-1], YT + 'x', ' ' + YT, 'watch?v=' + YT + '&v=' + YT,
                       'watch?v=' + YT + '&list=unknown', 'https://youtu.be/' + YT + 'https://youtu.be/' + YT,
                       'hhttps://youtu.be.evil.test/' + YT, 'hhttps://youtu.be/' + YT + '?t=1',
                       'hhttp://youtu.be/' + YT, 'https://unknown.test/' + YT):
            self.unchanged(video(source))

    def test_rutube_multiple_urls_queries_markup_and_extra_text_are_not_selected(self):
        for value in ('Synthetic ' + RT + ' ' + RT, 'Synthetic? ' + RT, '<b>Material</b> ' + RT,
                      'Synthetic ' + RT + ' trailing', RT.replace('/?p=', '?p='),
                      'Synthetic https://rutube.ru/video/' + RT_ID + '/', ' ' + RT):
            self.unchanged(video('https://youtu.be/' + YT, videoSrc2=value))

    def test_embedded_players_posters_meaningful_labels_and_unknown_fields_stay(self):
        for fields in ({'embeddedHtml': '<iframe></iframe>'}, {'posterSrc': 'https://example.test/image.png'},
                       {'anchor': 'section'}, {'html': 'Educational caption'}, {'unknown': None}):
            self.unchanged(video(**fields))

    def test_nested_material_conditions_or_style_content_are_protected(self):
        child = video(); child['children'] = [{'name': 'text', 'fields': {'html': '<p>Instruction</p>'}}]
        condition = video(); condition['visibleConditions'] = []
        styled = video(); styled['style'] = {'caption': 'Additional instruction'}
        for node in (child, condition, styled): self.unchanged(node)

    def test_provider_and_video_node_order_are_never_reassigned(self):
        source = page(video(YT, videoProvider='vimeo'), {'name': 'section', 'children': [video()]})
        out, changes = self.normalize(source)
        self.assertEqual(out['children'][0], source['children'][0])
        self.assertEqual(changes[0]['path'], [1, 0]); self.assertEqual(out['children'][1]['children'][0]['id'], 'source-video')

    def test_valid_urls_and_second_pass_keep_exact_payload_fingerprint(self):
        source = payload(page(video('https://youtu.be/' + YT))); before = json.dumps(source, sort_keys=True)
        ape, changes = self.normalize(source['ape']); after = copy.deepcopy(source); after['ape'] = ape
        self.assertEqual(changes, []); self.assertEqual(json.dumps(after, sort_keys=True), before)
        self.assertEqual(_core().plan_import(source), _core().plan_import(after))
        fixed, _ = self.normalize(page(video())); again, changes = self.normalize(fixed)
        self.assertEqual((again, changes), (fixed, []))

    def test_invalid_tree_or_validator_uses_fixed_review_codes(self):
        for ape in (None, [], {'name': 'text'}, page('bad'), page({'name': 'video', 'fields': []})):
            with self.assertRaisesRegex(Review, '^native_video_sources_invalid$'): self.normalize(ape)
        with self.assertRaisesRegex(Review, '^native_video_sources_validator_invalid$'):
            mod.normalize_native_video_sources(page(), None)


if __name__ == '__main__': unittest.main()

import copy
import json
import unittest
from unittest.mock import patch

from importer import Review
import normalize_reviewed_legacy_players as subject
from normalize_editor_nodes import _core
from normalize_source import normalize_payload, static_validator


FRAME = ('<iframe src="https://www.youtube.com/embed/abcdefghijk" width="560" height="315" '
         'allow="accelerometer; autoplay; encrypted-media; gyroscope; picture-in-picture" '
         'frameborder="0" allowfullscreen=""></iframe>')
SECOND = FRAME.replace('abcdefghijk', '12345678901')
SUFFIX = '\r\n\r\n<p><a href="https://docs.google.com/document/d/synthetic/edit" target="_blank">Презентация &amp; текст</a></p>'
VK = ('<iframe src="https://vkvideo.ru/video_ext.php?oid=-123&amp;id=456&amp;hash=abcdef0123456789&amp;hd=4" '
      'width="1920" height="1080" allow="autoplay; encrypted-media; fullscreen; picture-in-picture; screen-wake-lock;" '
      'frameborder="0" allowfullscreen></iframe>')
TAIL = 'https://www.youtube.com/embed/abcdefghijk?rel=0&controls=1&showinfo=0" frameborder="0'


def root(node):
    return {'name': 'page', 'children': [node]}


def text(html=None):
    return {'id': 'synthetic-text', 'name': 'text', 'fields': {'html': html if html is not None else '<p>' + FRAME + '</p>' + SUFFIX},
            'style': {'lists': {'text': {'paddingTop': {'value': {'number': 20, 'units': 'px'}}}}}}


def video(vk=True):
    fields = {'videoProvider': 'embedded' if vk else 'youtube', 'nativePlayer': False,
              'embeddedHtml': VK if vk else '', 'videoSrc': '' if vk else TAIL,
              'anchor': '', 'posterSrc': '', 'html': '' if vk else 'Видео'}
    if vk:
        fields.update(videoProvider2='rutube', videoSrc2='', nativePlayer2=False, posterSrc2='',
                      isFloating=None, isShowFastRewindButtons=True, isShowFastRewindButtons2=True,
                      isShowProgressControl=True, isShowProgressControl2=True)
    return {'id': 'synthetic-video', 'name': 'video', 'fields': fields, 'style': {}}


def bind(node, kind='mixed_youtube', extra=1, context=(21, 27), path=(0,)):
    return patch.object(subject, 'BINDINGS', {context: ((path, subject._sha(node), kind, extra),)})


def normalize(ape, context=(21, 27)):
    return subject.normalize_reviewed_legacy_players(ape, *context, static_validator())


def payload(ape, context=(21, 27)):
    return {'account': 'mastervision', 'source_origin': 'https://shop.mastervision.su', 'format': 'ape',
            'course_id': context[0], 'lesson_id': context[1], 'course_title': 'Synthetic course',
            'lesson_title': 'Synthetic lesson', 'ape': ape}


class ReviewedLegacyPlayersTests(unittest.TestCase):
    def test_split_preserves_exact_suffix_source_and_deterministic_replay(self):
        node = text(); ape = root(node); before = copy.deepcopy(ape)
        with bind(node):
            prepared, changes = normalize(ape)
            self.assertEqual(normalize(ape), (prepared, changes))
            self.assertEqual(normalize(prepared), (prepared, []))
        self.assertEqual(ape, before)
        group = prepared['children'][0]
        self.assertEqual(group['name'], 'section')
        self.assertEqual(group['style'], node['style'])
        self.assertEqual(group['children'][1]['fields']['html'], SUFFIX)
        self.assertEqual(group['children'][0]['fields']['videoSrc'], 'https://www.youtube.com/embed/abcdefghijk')
        self.assertEqual(changes[0]['association'], 'independent_sequential')
        self.assertNotIn('http', json.dumps(changes))

    def test_two_different_youtube_iframes_remain_distinct_sequential_videos(self):
        node = text('<p>' + FRAME + SECOND + '</p>' + SUFFIX)
        with bind(node, extra=2): prepared, changes = normalize(root(node))
        children = prepared['children'][0]['children']
        self.assertEqual([n['name'] for n in children], ['video', 'video', 'text'])
        self.assertEqual([n['fields']['videoSrc'].split('/')[-1] for n in children[:2]], ['abcdefghijk', '12345678901'])
        self.assertEqual(len({n['id'] for n in children}), 3)
        self.assertEqual(changes[0]['video_count'], 2)
        full, _ = normalize_payload(payload(prepared))
        plan = _core().plan_import(full)
        self.assertTrue(plan['ready'], plan['issues'])
        self.assertEqual([b['type'] for b in plan['blocks']], ['videoChoice', 'videoChoice', 'paragraph'])
        for block in plan['blocks'][:2]: self.assertFalse(block['data'].get('rutube'))

    def test_wrong_identity_or_path_or_source_or_odd_id_is_unchanged(self):
        node = text(); ape = root(node)
        with bind(node):
            for context in ((21, 28), (22, 27), (True, 27), ('021', 27)):
                self.assertEqual(normalize(ape, context), (ape, []))
            changed = copy.deepcopy(ape); changed['children'][0]['fields']['html'] += 'changed'
            self.assertEqual(normalize(changed), (changed, []))
            moved = {'name': 'page', 'children': [{'name': 'section', 'children': [node]}]}
            self.assertEqual(normalize(moved), (moved, []))
            self.assertEqual(normalize(ape, ('21', '27'))[0]['children'][0]['name'], 'section')

    def test_no_visible_text_or_other_media_may_be_discarded_from_first_paragraph(self):
        bad = ['<p>Keep me' + FRAME + '</p>' + SUFFIX,
               '<p>' + FRAME + '<span>Keep me</span></p>' + SUFFIX,
               '<p class="unknown">' + FRAME + '</p>' + SUFFIX,
               '<p>' + FRAME + '<!-- comment --></p>' + SUFFIX,
               '<p>' + FRAME + SECOND + '</p>' + SUFFIX]
        for html in bad:
            node = text(html)
            with self.subTest(html=html), bind(node), self.assertRaises(Review): normalize(root(node))

    def test_mixed_unsafe_materials_and_frames_are_not_accepted(self):
        for html in ('<p>' + FRAME.replace('www.youtube.com', 'example.org') + '</p>' + SUFFIX,
                     '<p>' + FRAME.replace('frameborder="0"', 'frameborder="0" onload="bad()"') + '</p>' + SUFFIX,
                     '<p>' + FRAME + '</p><script>bad()</script>',
                     '<p>' + FRAME + '</p><p><a href="javascript:bad()">Keep</a></p>'):
            node = text(html)
            with self.subTest(html=html), bind(node), self.assertRaises(Review): normalize(root(node))

    def test_unknown_fields_children_and_authored_styles_cannot_be_dropped(self):
        nodes = []
        for key, value in [('visibleConditions', {'purchase': 1}), ('newType', 'Keep me')]:
            n = text(); n['fields'][key] = value; nodes.append(n)
        n = text(); n['children'] = [{'name': 'text', 'fields': {'html': '<p>Keep</p>'}}]; nodes.append(n)
        for value in (None, False, 0, {}):
            n = text(); n['children'] = value; nodes.append(n)
        n = text(); n['style']['caption'] = 'Keep me'; nodes.append(n)
        n = text(); n['style']['backgroundImage'] = 'https://example.org/keep.jpg'; nodes.append(n)
        n = text(); n['unknown'] = 'Keep me'; nodes.append(n)
        for node in nodes:
            with self.subTest(node=node), bind(node), self.assertRaises(Review): normalize(root(node))

    def test_malformed_attribute_tail_keeps_same_id_all_controls_and_query(self):
        node = video(False); before = copy.deepcopy(node)
        with bind(node, 'youtube_attribute_tail', None): prepared, changes = normalize(root(node))
        got = prepared['children'][0]
        expected = copy.deepcopy(node); expected['fields']['videoSrc'] = TAIL.removesuffix('" frameborder="0')
        self.assertEqual(got, expected); self.assertEqual(node, before)
        self.assertIs(changes[0]['same_video_id'], True)
        self.assertIs(changes[0]['query_preserved'], True)
        full, _ = normalize_payload(payload(prepared))
        self.assertTrue(_core().plan_import(full)['ready'])

    def test_tail_repair_does_not_select_urls_or_remove_arbitrary_suffix(self):
        for suffix in ('" frameborder="1', ' arbitrary', '" frameborder="0 extra', '\n'):
            node = video(False); node['fields']['videoSrc'] = TAIL.removesuffix('" frameborder="0') + suffix
            with self.subTest(suffix=suffix), bind(node, 'youtube_attribute_tail', None), self.assertRaises(Review): normalize(root(node))
        for key, value in [('videoSrc2', 'https://youtu.be/12345678901'), ('posterSrc', 'https://example.org/poster.jpg'), ('nativePlayer', True)]:
            node = video(False); node['fields'][key] = value
            with bind(node, 'youtube_attribute_tail', None), self.assertRaises(Review): normalize(root(node))

    def test_vk_preserves_exact_html_and_independent_audio_neighbour(self):
        node = video(); ape = root(node)
        ape['children'].insert(0, {'name': 'text', 'fields': {'html': '<p><a href="https://example.org/audio">Audio</a></p>'}})
        with bind(node, 'vk', None, path=(1,)): prepared, changes = normalize(ape)
        self.assertEqual(prepared['children'][0], ape['children'][0])
        self.assertEqual(prepared['children'][1]['fields'], {'html': VK})
        self.assertEqual(changes[0]['association'], 'independent')
        self.assertNotIn('group_path', changes[0])
        full, _ = normalize_payload(payload(prepared)); plan = _core().plan_import(full)
        self.assertTrue(plan['ready'], plan['issues'])
        self.assertEqual([b['type'] for b in plan['blocks']], ['paragraph', 'htmlBlock'])

    def test_vk_explicit_group_metadata_does_not_pair_adjacent_sources(self):
        node = video()
        with bind(node, 'vk', (0,)): prepared, changes = normalize(root(node))
        self.assertEqual(changes[0]['group_path'], [0])
        self.assertEqual(changes[0]['association'], 'explicit_alternative_group')
        self.assertEqual(prepared['children'][0]['fields']['html'], VK)
        self.assertIs(changes[0]['embedded_html_unchanged'], True)

    def test_vk_unknown_host_or_features_or_hidden_payload_is_rejected(self):
        for field, value in [('embeddedHtml', VK.replace('vkvideo.ru', 'example.org')),
                             ('embeddedHtml', VK.replace('allow="', 'onload="bad()" allow="')),
                             ('embeddedHtml', VK.replace('screen-wake-lock;', 'camera;')),
                             ('embeddedHtml', VK + '<p>Keep me</p>'),
                             ('html', 'Keep me'), ('videoSrc', 'https://youtu.be/abcdefghijk'),
                             ('isFloating', True), ('posterSrc', 'https://example.org/poster.png'),
                             ('isShowProgressControl', 1)]:
            node = video(); node['fields'][field] = value
            with self.subTest(field=field, value=value), bind(node, 'vk', None), self.assertRaises(Review): normalize(root(node))

    def test_account_root_and_validator_guards(self):
        with patch.object(subject, 'ACCOUNT', 'mv-centr'), self.assertRaisesRegex(Review, 'account_mismatch'):
            normalize(root(text()))
        for ape in ([], {'name': 'not-page'}, None, {'name': 'page', 'children': None}):
            with self.assertRaisesRegex(Review, 'source_invalid'): normalize(ape)
        with self.assertRaisesRegex(Review, 'source_invalid'):
            subject.normalize_reviewed_legacy_players(root(text()), 21, 27, None)


if __name__ == '__main__': unittest.main()

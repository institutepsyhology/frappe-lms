"""Absent material destinations must not block otherwise complete synthetic lessons."""
import copy
import json
import unittest

from importer import Review
from normalize_editor_nodes import _core
from normalize_source import static_validator
import normalize_empty_material_buttons as mod


def button(label='АУДИОЗАПИСЬ', **fields):
    return {'id': 'audio-button', 'name': 'button', 'fields': {
        'anchor': '', 'html': label, 'icon': '', 'linkType': 'url', 'url': '',
        'blank': True, 'toAnchor': '', 'event': '', **fields},
        'style': {'spacing': {'margin': '12px'}}, 'children': []}


def page(*children): return {'name': 'page', 'children': list(children)}
def text(value='Keep educational text'): return {'name': 'text', 'fields': {'html': '<p>' + value + '</p>'}}
def payload(ape):
    return {'account': 'mastervision', 'source_origin': 'https://shop.mastervision.su',
            'course_id': 1, 'lesson_id': 2, 'course_title': 'Synthetic course',
            'lesson_title': 'Synthetic lesson', 'format': 'ape', 'ape': ape}


class EmptyMaterialButtonTests(unittest.TestCase):
    def normalize(self, ape): return mod.normalize_empty_material_buttons(ape, static_validator())

    def test_observed_plain_and_formatted_audio_and_material_labels(self):
        labels = ['АУДИОЗАПИСЬ', 'МАТЕРИАЛЫ', '<span style="font-size: 16px; line-height: 1.5;">АУДИОЗАПИСЬ</span>',
                  '<strong>МАТЕРИАЛЫ</strong>']
        source = page(*(button(label) for label in labels), text())
        original = copy.deepcopy(source)
        out, changes = self.normalize(source)
        self.assertEqual(source, original)
        self.assertEqual(out, page(text()))
        self.assertEqual(changes, [{'path': [i], 'code': mod.CODE} for i in range(4)])

    def test_missing_or_null_url_qualifies_but_never_a_whitespace_url(self):
        missing = button(); del missing['fields']['url']
        source = page(missing, button(url=None), button(url=' '))
        out, changes = self.normalize(source)
        self.assertEqual(out, page(source['children'][2]))
        self.assertEqual([c['path'] for c in changes], [[0], [1]])

    def test_original_nested_paths_and_surrounding_order_are_preserved(self):
        video = {'name': 'video', 'fields': {'videoProvider': 'youtube', 'videoSrc': 'https://youtu.be/AbCdEfGhI12'}}
        source = page(text('First'), {'name': 'section', 'children': [button(), video, button('МАТЕРИАЛЫ'), text('Last')]})
        out, changes = self.normalize(source)
        self.assertEqual(changes, [{'path': [1, 0], 'code': mod.CODE}, {'path': [1, 2], 'code': mod.CODE}])
        self.assertEqual(out, page(text('First'), {'name': 'section', 'children': [video, text('Last')]}))

    def test_second_pass_is_identical_and_has_no_more_omissions(self):
        out, _ = self.normalize(page(button(), text()))
        again, changes = self.normalize(out)
        self.assertEqual((again, changes), (out, []))

    def test_all_nonempty_and_nonstring_destinations_remain_exact(self):
        for url in ('https://example.test/audio.mp3', ' https://example.test/audio.mp3 ', '{goods_ordering_1}',
                    'javascript:alert(1)', ' ', [], {}, False, 0):
            source = page(button(url=url))
            with self.subTest(url_type=type(url).__name__):
                self.assertEqual(self.normalize(source), (source, []))

    def test_unrecognized_and_other_actions_are_never_omitted(self):
        for label in ('АУДИОЗАПИСЬ 2', 'МАТЕРИАЛЫ И ЗАДАНИЕ', 'ПРЕЗЕНТАЦИЯ', '', 'Вопрос тренеру',
                      'Оставить заявку менеджеру', 'АУДИОЗАПИСЬ — добавим позже', 'АУДИОЗАПИCЬ'):
            source = page(button(label))
            with self.subTest(label=label): self.assertEqual(self.normalize(source), (source, []))

    def test_behaviors_icons_anchors_and_non_url_buttons_stay(self):
        for fields in ({'anchor': 'part'}, {'icon': 'download'}, {'event': 'checkout'}, {'toAnchor': 'part'},
                       {'linkType': 'event'}, {'linkType': 'anchor'}, {'icon': {}}, {'event': []}, {'unknown': None}):
            source = page(button(**fields))
            with self.subTest(fields=list(fields)): self.assertEqual(self.normalize(source), (source, []))

    def test_children_and_unknown_node_settings_are_protected(self):
        child = button(); child['children'] = [text()]
        extra = button(); extra['visibleConditions'] = []
        for node in (child, extra):
            source = page(node); self.assertEqual(self.normalize(source), (source, []))

    def test_meaningful_style_content_is_never_removed(self):
        for style in ({'caption': 'Educational caption'}, {'background': 'url(https://example.test/picture.jpg)'},
                      {'html': '<p>Instructions</p>'}):
            node = button(); node['style'] = style; source = page(node)
            self.assertEqual(self.normalize(source), (source, []))

    def test_unsafe_or_non_inline_label_markup_is_protected(self):
        for label in ('<a href="https://example.test">АУДИОЗАПИСЬ</a>', '<img alt="АУДИОЗАПИСЬ">',
                      '<span onclick="alert(1)">АУДИОЗАПИСЬ</span>', '<script>АУДИОЗАПИСЬ</script>',
                      '<span>АУДИОЗАПИСЬ</span><!-- extra -->', '<iframe>МАТЕРИАЛЫ</iframe>'):
            source = page(button(label)); self.assertEqual(self.normalize(source), (source, []))

    def test_invalid_blank_flags_are_not_silently_normalized(self):
        for flag in ('true', [], {}, 2, 0.0):
            source = page(button(blank=flag)); self.assertEqual(self.normalize(source), (source, []))

    def test_static_validator_refusal_preserves_original_button(self):
        def refuse(markup): raise ValueError('synthetic refusal')
        source = page(button('<strong>АУДИОЗАПИСЬ</strong>'))
        self.assertEqual(mod.normalize_empty_material_buttons(source, refuse), (source, []))

    def test_real_core_lesson_preserves_video_and_educational_links(self):
        video = {'name': 'video', 'fields': {'videoProvider': 'youtube', 'videoSrc': 'https://youtu.be/AbCdEfGhI12'}}
        link = button('ПРЕЗЕНТАЦИЯ', url='https://example.test/notes.pdf')
        source = payload(page(video, link, button(), text()))
        before = _core().plan_import(source)
        self.assertEqual(before['issues'], ['unsupported_button'])
        normalized, changes = self.normalize(source['ape'])
        after = copy.deepcopy(source); after['ape'] = normalized
        plan = _core().plan_import(after)
        expected = _core().plan_import(payload(page(video, link, text())))
        self.assertTrue(plan['ready']); self.assertEqual(plan['blocks'], expected['blocks'])
        self.assertEqual(len(changes), 1)

    def test_empty_lesson_stays_for_review_without_invented_content(self):
        ape, changes = self.normalize(page(button(), button('МАТЕРИАЛЫ')))
        plan = _core().plan_import(payload(ape))
        self.assertEqual(len(changes), 2); self.assertEqual(plan['blocks'], [])
        self.assertEqual(plan['issues'], ['empty_lesson']); self.assertFalse(plan['ready'])

    def test_already_ready_payload_keeps_exact_fingerprint_and_core_output(self):
        source = payload(page(button(url='https://example.test/audio.mp3'), text()))
        before = json.dumps(source, sort_keys=True, separators=(',', ':'))
        ape, changes = self.normalize(source['ape']); after = copy.deepcopy(source); after['ape'] = ape
        self.assertEqual(changes, []); self.assertEqual(json.dumps(after, sort_keys=True, separators=(',', ':')), before)
        self.assertEqual(_core().plan_import(after), _core().plan_import(source))

    def test_invalid_tree_or_validator_uses_fixed_review_codes(self):
        for source in (None, [], {'name': 'text', 'children': []}, page('bad'), page({'name': 'button', 'fields': []})):
            with self.assertRaisesRegex(Review, '^empty_material_buttons_invalid$'): self.normalize(source)
        with self.assertRaisesRegex(Review, '^empty_material_buttons_validator_invalid$'):
            mod.normalize_empty_material_buttons(page(), None)


if __name__ == '__main__': unittest.main()

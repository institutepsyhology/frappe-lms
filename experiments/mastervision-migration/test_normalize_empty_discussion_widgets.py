"""Synthetic empty-shell recognition never deletes authored content or answers."""
import copy
import json
import unittest

from importer import Review
from normalize_editor_nodes import _core
from normalize_source import static_validator
import normalize_empty_discussion_widgets as mod


ANSWER = ('<div class="xdget-block xdget-lessonAnswers xdget-visible-to-bg-" data-xdget-id="123" id="xdget123">'
          '<div class="row row-section"><div class="col-md-12"><div class="other-answers answers-list">'
          '</div></div></div></div>')
TALKS = '<div class="talks-widget activated-talks-widget" id="w456"></div>'
BUTTON = '<div class="talks-widget-button"></div>'
MATERIAL = '<p><strong>Read &amp; practise</strong> <a href="https://example.test/file?one=1&amp;two=2">Notes</a></p>'
SOURCE = '<div>' + MATERIAL + ANSWER + TALKS + BUTTON + '<p>Keep the instructions.</p></div>'
CLEANED = '<div>' + MATERIAL + '<p>Keep the instructions.</p></div>'


def page(*children): return {'name': 'page', 'children': list(children)}
def text(source=SOURCE, **fields): return {'id': 'source-text', 'name': 'text', 'fields': {'html': source, **fields}, 'style': {'spacing': {'margin': '12px'}}}
def payload(ape):
    return {'account': 'mastervision', 'source_origin': 'https://shop.mastervision.su',
            'course_id': 1, 'lesson_id': 2, 'course_title': 'Synthetic course',
            'lesson_title': 'Synthetic lesson', 'format': 'ape', 'ape': ape}


class DiscussionWidgetTests(unittest.TestCase):
    def normalize(self, ape): return mod.normalize_empty_discussion_widgets(ape, static_validator())
    def unchanged(self, source):
        ape = page(text(source)); self.assertEqual(self.normalize(ape), (ape, []))

    def test_exact_empty_bundle_is_sliced_without_changing_any_other_byte(self):
        ape = page(text()); before = copy.deepcopy(ape)
        out, changes = self.normalize(ape)
        expected = copy.deepcopy(ape); expected['children'][0]['fields']['html'] = CLEANED
        self.assertEqual(ape, before); self.assertEqual(out, expected)
        self.assertEqual(changes, [{'path': [0], 'code': mod.CODE, 'widgets': 3}])

    def test_only_indentation_and_verified_nbsp_placeholders_are_discarded(self):
        source = SOURCE
        for fragment in (ANSWER, TALKS, BUTTON):
            source = source.replace(fragment, fragment.replace('></div>', '> \n\t</div>'))
        out, changes = self.normalize(page(text(source)))
        self.assertEqual(out['children'][0]['fields']['html'], CLEANED)
        self.assertEqual(len(changes), 1)
        nbsp = SOURCE.replace('</div>', '&nbsp;</div>', 1)
        out, changes = self.normalize(page(text(nbsp)))
        self.assertEqual(out['children'][0]['fields']['html'], CLEANED)
        self.assertEqual(len(changes), 1)
        for visible in ('\u200b', 'A learner answer'):
            self.unchanged(SOURCE.replace('</div></div></div></div>', visible + '</div></div></div></div>', 1))

    def test_real_core_rejects_original_and_accepts_preserved_material(self):
        original = payload(page(text())); before = _core().plan_import(original)
        self.assertIn('unsafe_or_unrecognized_html', before['issues'])
        ape, _ = self.normalize(original['ape']); converted = copy.deepcopy(original); converted['ape'] = ape
        after = _core().plan_import(converted)
        self.assertTrue(after['ready']); self.assertEqual(after['issues'], [])
        expected = _core().plan_import(payload(page(text(CLEANED))))
        self.assertEqual(after['blocks'], expected['blocks'])

    def test_material_between_and_after_widgets_remains_exact(self):
        middle = '<p>New material <a href="http://example.test/form">Questionnaire</a></p>'
        source = SOURCE.replace(TALKS, middle + TALKS)
        out, changes = self.normalize(page(text(source)))
        expected = source.replace(ANSWER, '').replace(TALKS, '').replace(BUTTON, '')
        self.assertEqual(out['children'][0]['fields']['html'], expected); self.assertEqual(len(changes), 1)

    def test_links_images_inputs_forms_and_script_in_widget_are_protected(self):
        for extra in ('<a href="https://example.test/answer">Attachment</a>', '<img src="https://example.test/image.png">',
                      '<input value="learner data">', '<form></form>', '<script>throw new Error("must not execute")</script>',
                      '<iframe src="https://example.test"></iframe>'):
            self.unchanged(SOURCE.replace(TALKS, TALKS.replace('</div>', extra + '</div>')))

    def test_comments_hidden_text_and_declarations_are_not_silently_dropped(self):
        for extra in ('<!-- learner answer -->', '<!DOCTYPE html>', '<?task value?>',
                      '<div style="display:none">Hidden educational text</div>'):
            self.unchanged(SOURCE.replace(BUTTON, BUTTON.replace('</div>', extra + '</div>')))

    def test_unknown_attributes_events_and_class_names_are_protected(self):
        for changed in (TALKS.replace(' id=', ' onclick="send()" id='), TALKS.replace(' id=', ' data-extra="" id='),
                        TALKS.replace('talks-widget activated-talks-widget', 'talks-widget other-widget'),
                        BUTTON.replace('class=', 'href="https://example.test" class=')):
            self.unchanged(SOURCE.replace(TALKS if 'talks-widget-button' not in changed else BUTTON, changed))

    def test_unknown_css_or_urls_inside_styles_are_not_omitted(self):
        for style in ('position:fixed;', 'background:url(https://example.test/lesson.png);', 'color: red;'):
            self.unchanged(SOURCE.replace(TALKS, TALKS.replace(' id=', ' style="' + style + '" id=')))

    def test_known_empty_and_verified_css_are_accepted(self):
        for style in ('', 'box-sizing: border-box;'):
            source = SOURCE.replace('data-xdget-id=', 'style="' + style + '" data-xdget-id=', 1)
            out, changes = self.normalize(page(text(source)))
            self.assertEqual(out['children'][0]['fields']['html'], CLEANED); self.assertEqual(len(changes), 1)

    def test_numeric_widget_ids_must_match_the_observed_schema(self):
        for source in (SOURCE.replace('id="xdget123"', 'id="xdget124"'), SOURCE.replace('data-xdget-id="123"', 'data-xdget-id="abc"'),
                       SOURCE.replace('id="w456"', 'id="outside-widget"'), SOURCE.replace('id="w456"', 'id="w456" id="w457"')):
            self.unchanged(source)

    def test_source_links_targeting_a_widget_are_not_broken(self):
        for target in ('#xdget123', 'https://example.test/lesson#xdget123', '#%78dget123'):
            self.unchanged(SOURCE.replace('</div>', '</div><a href="' + target + '">Open answers</a>', 1))

    def test_missing_duplicate_reordered_and_malformed_bundles_stay_for_review(self):
        for source in (SOURCE.replace(ANSWER, ''), SOURCE.replace(TALKS, TALKS + TALKS), SOURCE.replace(ANSWER + TALKS, TALKS + ANSWER),
                       SOURCE.replace(BUTTON, BUTTON[:-6]), SOURCE.replace('<div class="row row-section">', '<span class="row row-section">')):
            self.unchanged(source)

    def test_final_static_validation_failure_keeps_the_original(self):
        self.unchanged(SOURCE + '<script>outsideWidget()</script>')
        def reject(source): raise ValueError('static refusal')
        ape = page(text()); self.assertEqual(mod.normalize_empty_discussion_widgets(ape, reject), (ape, []))

    def test_protected_parent_anchors_children_and_conditions_stay(self):
        anchored = text(anchor='important'); nested = text(); nested['children'] = [text('<p>Child material</p>')]
        conditional = text(); conditional['visibleConditions'] = []
        fields = text(extraSetting=None)
        for node in (anchored, nested, conditional, fields):
            ape = page(node); self.assertEqual(self.normalize(ape), (ape, []))

    def test_order_paths_identity_style_and_idempotence(self):
        ape = page(text('<p>Before</p>'), {'name': 'section', 'children': [text(), text('<p>After</p>')]})
        out, changes = self.normalize(ape)
        self.assertEqual(changes, [{'path': [1, 0], 'code': mod.CODE, 'widgets': 3}])
        self.assertEqual(out['children'][1]['children'][0]['id'], 'source-text')
        self.assertEqual(out['children'][1]['children'][0]['style'], ape['children'][1]['children'][0]['style'])
        again, changes = self.normalize(out); self.assertEqual((again, changes), (out, []))

    def test_already_valid_payload_is_exactly_unchanged(self):
        source = payload(page(text(CLEANED))); before = json.dumps(source, sort_keys=True)
        ape, changes = self.normalize(source['ape']); after = copy.deepcopy(source); after['ape'] = ape
        self.assertEqual(changes, []); self.assertEqual(json.dumps(after, sort_keys=True), before)
        self.assertEqual(_core().plan_import(source), _core().plan_import(after))

    def test_invalid_tree_and_validator_have_fixed_review_codes(self):
        for ape in (None, [], {'name': 'text'}, page('bad'), page({'name': 'text', 'fields': []})):
            with self.assertRaisesRegex(Review, '^empty_discussion_widgets_invalid$'): self.normalize(ape)
        with self.assertRaisesRegex(Review, '^empty_discussion_widgets_validator_invalid$'):
            mod.normalize_empty_discussion_widgets(page(), None)


if __name__ == '__main__': unittest.main()

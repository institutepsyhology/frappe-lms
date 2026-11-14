"""Source-bound trainer omissions and inert presentation changes preserve material."""
import copy
import hashlib
import json
import unittest
from unittest.mock import patch

from importer import Review
import normalize_reviewed_text_fragments as module
from normalize_source import static_validator


def digest(value): return hashlib.sha256(value.encode()).hexdigest()


def page(markup):
    return {'name': 'page', 'children': [{'name': 'text', 'id': 'witness',
            'fields': {'html': markup, 'anchor': ''}, 'style': {}}]}


class ReviewedTextTests(unittest.TestCase):
    def transform(self, markup, action):
        raw = page(markup); before = copy.deepcopy(raw)
        binding = {(990, 991): (((0,), digest(markup), action),)}
        with patch.dict(module.APPROVED, binding):
            output, changes = module.normalize_reviewed_text_fragments(raw, 990, 991, static_validator())
        self.assertEqual(raw, before)
        return output['children'][0]['fields']['html'], changes

    def test_remove_only_the_authorized_named_trainer_anchor(self):
        keep = '<p><a href="https://example.test/a">Presentation</a></p><hr />'
        trainer = '<p><a href="https://example.test/b">Задать вопрос тренеру курса Анне Ивановой</a></p>'
        result, changes = self.transform(keep + trainer, 'trainer')
        self.assertEqual(result, keep + '<p></p>')
        self.assertEqual(changes[0]['removed_links'], 1)

    def test_other_trainer_related_text_is_never_guessed(self):
        for text in ('Ответы тренера', 'Вопросы о тренере', 'Задать вопрос менеджеру'):
            with self.subTest(text=text), self.assertRaises(Review):
                self.transform('<p><a href="https://example.test/a">' + text + '</a></p>', 'trainer')

    def test_changed_source_is_a_failure(self):
        raw = page('<p>Changed</p>')
        with patch.dict(module.APPROVED, {(990, 991): (((0,), digest('<p>Original</p>'), 'trainer'),)}):
            with self.assertRaisesRegex(Review, 'reviewed_text_source_changed'):
                module.normalize_reviewed_text_fragments(raw, 990, 991, static_validator())

    def test_pricing_keeps_prices_strikethrough_and_link_attributes(self):
        markup = ('<h1>Course</h1><p><s>100</s> <strong>80</strong></p><center>'
                  '<a href="https://example.test/buy?a=1&amp;b=2" title="Order" style="'
                  + module.PRICING_STYLE + '">Order</a></center>')
        result, changes = self.transform(markup, 'pricing')
        self.assertIn('<s>100</s> <strong>80</strong>', result)
        self.assertIn('href="https://example.test/buy?a=1&amp;b=2" title="Order"', result)
        self.assertIn('background-color:rgb(0,102,204)', result)
        self.assertNotIn('linear-gradient', result)
        static_validator()(result)
        self.assertEqual(changes[0]['code'], module.PRICING_CODE)

    def test_unknown_pricing_css_and_missing_center_are_rejected(self):
        for markup in ('<center><a href="https://example.test/a" style="color:red">Order</a></center>',
                       '<a href="https://example.test/a" style="' + module.PRICING_STYLE + '">Order</a>'):
            with self.subTest(markup=markup), self.assertRaises(Review): self.transform(markup, 'pricing')

    def test_unbound_source_and_other_lesson_are_unchanged(self):
        raw = page('<p>Keep</p>')
        output, changes = module.normalize_reviewed_text_fragments(raw, 991, 990, static_validator())
        self.assertEqual((output, changes), (raw, []))

    def test_known_logical_padding_retains_ltr_indentation(self):
        source = '<h4 dir="ltr" style="padding-inline-start:48px">Keep</h4>'
        result, changes = self.transform(source, 'padding')
        self.assertEqual(result, '<h4 dir="ltr" style="padding-left:48px">Keep</h4>')
        self.assertEqual(changes[0]['code'], module.PADDING_CODE)

    def test_padding_does_not_guess_rtl_or_other_sizes(self):
        for source in ('<h4 dir="rtl" style="padding-inline-start:48px">Keep</h4>',
                       '<h4 style="padding-inline-start:49px">Keep</h4>'):
            with self.subTest(source=source), self.assertRaises(Review): self.transform(source, 'padding')

    def test_padding_keeps_heading_and_omits_only_its_inert_aria_role(self):
        source = '<p role="presentation">Keep</p><h4 role="presentation" style="padding-inline-start:48px">Heading</h4>'
        result, _ = self.transform(source, 'padding')
        self.assertEqual(result, '<p role="presentation">Keep</p><h4 style="padding-left:48px">Heading</h4>')

    def test_authored_or_changed_style_never_disappears(self):
        markup = '<p><a href="https://example.test/a">Задать вопрос тренеру курса Анне Ивановой</a></p>'
        raw = page(markup); binding = {(990,991):(((0,),digest(markup),'trainer'),)}
        with patch.dict(module.APPROVED,binding):
            raw['children'][0]['style']={'caption':'Keep this authored content'}
            with self.assertRaisesRegex(Review,'reviewed_text_source_changed'):
                module.normalize_reviewed_text_fragments(raw,990,991,static_validator())
            raw['children'][0]['style']={'lists':{'text':{'opacity':{'value':{'number':0}}}}}
            with patch.dict(module.STYLE_BINDINGS,{(990,991,(0,)):digest('{}')}):
                with self.assertRaisesRegex(Review,'reviewed_text_source_changed'):
                    module.normalize_reviewed_text_fragments(raw,990,991,static_validator())


if __name__ == '__main__': unittest.main()

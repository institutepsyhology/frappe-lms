from copy import deepcopy
import json
import unittest
from unittest.mock import patch

from import_capture import ARCHIVE, Review, plan_import
import normalize_psychotherapy_materials as repair


def lesson(children):
    return {'account': 'iomp', 'source_origin': 'https://shop.iomp.ru', 'format': 'ape',
            'course_id': 193, 'lesson_id': 3280, 'ape': {'name': 'page', 'children': children}}


class PsychotherapyMaterialTests(unittest.TestCase):
    def test_only_reviewed_button_is_removed_in_the_right_lesson(self):
        button = {'name': 'button', 'fields': {'html': '<span>АНКЕТА</span>', 'url': 'fixture'}}
        text = {'name': 'text', 'fields': {'html': 'Заполните анкету'}}
        other = {'name': 'button', 'fields': {'html': 'Материалы', 'url': 'same'}}
        payload = lesson([text, button, other])
        with patch.object(repair, 'QUESTIONNAIRE_BUTTON', repair._digest(button)):
            for fields in [{'course_id': 192}, {'lesson_id': 3260}, {'account': 'mastervision'},
                           {'source_origin': 'https://shop.mv-centr.ru'}]:
                foreign = dict(deepcopy(payload), **fields)
                before = deepcopy(foreign)
                repair.omit_questionnaire_button(foreign)
                self.assertEqual(foreign, before)
            changed = deepcopy(payload)
            changed['ape']['children'][1]['fields']['url'] = 'corrected'
            with self.assertRaisesRegex(Review, 'questionnaire_button_changed'):
                repair.omit_questionnaire_button(changed)
            repair.omit_questionnaire_button(payload)
            repair.omit_questionnaire_button(payload)
        self.assertEqual(payload['ape']['children'], [text, other])

    def test_deferred_presentation_is_scoped_to_iomp_course_193_lesson_3260(self):
        deferred = dict(lesson([]), lesson_id='3260')
        self.assertTrue(repair.awaiting_presentation_decision(deferred))
        for changes in [{'account': 'mastervision'}, {'source_origin': 'https://shop.mastervision.su'},
                        {'course_id': '194'}, {'lesson_id': 3280}]:
            self.assertFalse(repair.awaiting_presentation_decision(dict(deferred, **changes)))

    def test_saved_questionnaire_converts_with_text_and_no_button(self):
        captures = sorted((ARCHIVE / 'course-193').rglob('lesson-3280.json'))
        if not captures:
            self.skipTest('private capture unavailable')
        payload = json.loads(captures[-1].read_text(encoding='utf-8'))['payload']
        original = deepcopy(payload['ape']['children'])
        self.assertEqual(original[-1]['name'], 'button')
        repair.omit_questionnaire_button(payload)
        self.assertTrue(payload['ape']['children'] == original[:-1])
        plan = plan_import(payload, {})
        self.assertEqual(plan['issues'], [])
        self.assertEqual([block['type'] for block in plan['blocks']], ['paragraph'])


if __name__ == '__main__':
    unittest.main()

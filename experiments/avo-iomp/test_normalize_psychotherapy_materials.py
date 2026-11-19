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

    def test_supervision_materials_are_scoped_to_iomp_course_193_lesson_3260(self):
        deferred = dict(lesson([{'name': 'section', 'children': []}]), lesson_id='3260')
        for changes in [{'account': 'mastervision'}, {'source_origin': 'https://shop.mastervision.su'},
                        {'course_id': '194'}, {'lesson_id': 3280}]:
            payload = dict(deepcopy(deferred), **changes)
            before = deepcopy(payload)
            repair.omit_supervision_presentation(payload)
            self.assertEqual(payload, before)
        with self.assertRaisesRegex(Review, 'supervision_materials_changed'):
            repair.omit_supervision_presentation(deferred)

    def test_archived_supervision_layouts_keep_the_audio_and_video_pair(self):
        captures = sorted((ARCHIVE / 'course-193').rglob('lesson-3260.json'))
        if not captures:
            self.skipTest('private capture unavailable')
        for capture in captures:
            with self.subTest(capture=capture.parent.name):
                payload = json.loads(capture.read_text(encoding='utf-8'))['payload']
                nodes = payload['ape']['children']
                before = deepcopy(nodes[:-1])
                audio = deepcopy(nodes[-1]['children'][-1]['children'][0])
                repair.omit_supervision_presentation(payload)
                repair.omit_supervision_presentation(payload)
                self.assertEqual(nodes[:-1], before)
                self.assertEqual(len(nodes[-1]['children']), 1)
                audio['fields']['html'] = 'АУДИОЗАПИСЬ'
                self.assertTrue(nodes[-1]['children'][0]['children'] == [audio])
                plan = plan_import(payload, {})
                self.assertEqual(plan['issues'], [])
                self.assertEqual([b['type'] for b in plan['blocks']], ['videoChoice', 'paragraph'])

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

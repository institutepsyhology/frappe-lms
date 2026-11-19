import copy
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from import_capture import ARCHIVE, Review, plan_import
import normalize_life_position as repair


def capture(course, lesson):
    files = sorted((ARCHIVE / f'course-{course}').rglob(f'lesson-{lesson}.json'))
    if not files:
        raise unittest.SkipTest('private capture unavailable')
    return json.loads(files[-1].read_text(encoding='utf-8'))['payload']


class LifePositionTests(unittest.TestCase):
    def test_target_identity_and_unknown_source(self):
        payload = dict(account='iomp', source_origin='https://shop.iomp.ru', format='ape',
                       course_id='172', lesson_id='2881', ape={'name': 'page'})
        before = copy.deepcopy(payload)
        repair.normalize_life_position(payload, None)
        self.assertEqual(payload, before)
        payload['lesson_id'] = '2882'
        for choice, error in ((None, 'source_changed'), ('other', 'presentation_unknown')):
            with self.assertRaisesRegex(Review, error):
                repair.normalize_life_position(payload, None, choice)
        self.assertEqual(payload['ape'], before['ape'])

    def test_missing_foreign_or_changed_donor(self):
        donor = dict(account='iomp', source_origin='https://shop.iomp.ru', format='ape',
                     course_id=116, lesson_id=1886, ape={'name': 'page'})
        expected = repair._digest(donor['ape'])
        with (patch.dict(repair.DONORS, powerpoint=(116, 1886, expected)),
              patch.object(Path, 'rglob', return_value=[]) as files,
              patch.object(Path, 'read_text') as read):
            with self.assertRaisesRegex(Review, 'donor_missing'):
                repair._read_donor(Path('archive'), 'powerpoint')
            files.return_value = [Path('a'), Path('b')]
            original = json.dumps({'payload': donor})
            for changed in ({**donor, 'account': 'other'}, {**donor, 'ape': {'name': 'changed'}}):
                read.side_effect = [original, json.dumps({'payload': changed})]
                with self.assertRaisesRegex(Review, 'donor_changed'):
                    repair._read_donor(Path('archive'), 'powerpoint')

    def test_real_capture_keeps_order_other_materials_and_review(self):
        original = capture(172, 2882)
        donor = capture(116, 1886)
        expected_pairs = [b['data'] for b in plan_import(donor, {})['blocks'] if b['type'] == 'videoChoice']
        buttons = repair._buttons(original['ape'], 3)
        for choice in (None, 'powerpoint', 'pdf'):
            with self.subTest(choice=choice):
                payload = copy.deepcopy(original)
                repair.normalize_life_position(payload, ARCHIVE)
                repair.normalize_life_position(payload, ARCHIVE, choice)
                prepared = copy.deepcopy(payload)
                for repeat in (choice, None):
                    repair.normalize_life_position(payload, ARCHIVE, repeat)
                    self.assertTrue(payload == prepared)
                plan = plan_import(payload, {})
                self.assertEqual(plan['issues'], [] if choice else ['unsupported_button'])
                pairs = [b['data'] for b in plan['blocks'] if b['type'] == 'videoChoice']
                self.assertEqual(len(pairs), 2)
                self.assertTrue(pairs == expected_pairs)
                actual_buttons = repair._buttons(payload['ape'], 3)
                self.assertTrue(actual_buttons[1:] == buttons[1:])
                source_buttons = {'powerpoint': repair._buttons(donor['ape'], 4),
                                  'pdf': repair._buttons(capture(88, 1029)['ape'], 3)}
                self.assertTrue(actual_buttons[0]['url'] == source_buttons.get(choice, buttons)[0]['url'])
                # Reversing only the requested edits must recover every original field.
                for node in payload['ape']['children'][1:3]:
                    node['fields'].pop('videoProvider2')
                    node['fields'].pop('videoSrc2')
                actual_buttons[0]['url'] = buttons[0]['url']
                self.assertTrue(payload == original)

    def test_failed_pdf_verification_leaves_target_untouched(self):
        payload = capture(172, 2882)
        before = copy.deepcopy(payload)
        read = repair._read_donor

        def changed(archive, choice):
            donor = read(archive, choice)
            if choice == 'pdf':
                repair._buttons(donor['ape'], 3)[2]['url'] = 'changed'
            return donor

        with patch.object(repair, '_read_donor', side_effect=changed):
            with self.assertRaisesRegex(Review, 'materials_mismatch'):
                repair.normalize_life_position(payload, ARCHIVE, 'pdf')
        self.assertTrue(payload == before)

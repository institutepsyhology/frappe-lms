import copy
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from import_capture import ARCHIVE, Review, plan_import
from normalize_supervision_media import normalize_supervision_media


def archived(course, lesson):
    copies = sorted((ARCHIVE / f'course-{course}').rglob(f'lesson-{lesson}.json'))
    if not copies:
        raise unittest.SkipTest('private capture unavailable')
    return json.loads(copies[-1].read_text(encoding='utf-8'))['payload']


class SupervisionMediaTests(unittest.TestCase):
    def test_limited_to_source_identity_and_reviewed_contents(self):
        payload = dict(account='mastervision', source_origin='https://shop.iomp.ru', format='ape',
                       course_id='202', lesson_id='4096', ape={'name': 'page'})
        before = copy.deepcopy(payload)
        normalize_supervision_media(payload, None)
        self.assertEqual(payload, before)
        payload['account'] = 'iomp'
        with self.assertRaisesRegex(Review, 'source_changed'):
            normalize_supervision_media(payload, None)

    def test_capture_receives_only_the_approved_fields_and_keeps_its_metadata(self):
        original = archived(202, 4096)
        donor = archived(221, 4103)
        payload = copy.deepcopy(original)
        normalize_supervision_media(payload, ARCHIVE)
        normalize_supervision_media(payload, ARCHIVE)
        donor_plan = plan_import(donor, {})
        plan = plan_import(payload, {})
        self.assertEqual(plan['issues'], [])
        self.assertEqual([b['type'] for b in plan['blocks']], ['videoChoice', 'paragraph', 'paragraph'])
        self.assertTrue(plan['blocks'][:2] == donor_plan['blocks'][:2])
        fields = payload['ape']['children'][1]['fields']
        fields.pop('videoProvider2')
        fields.pop('videoSrc2')
        fields['videoSrc'] = original['ape']['children'][1]['fields']['videoSrc']
        payload['ape']['children'][2]['fields']['url'] = original['ape']['children'][2]['fields']['url']
        self.assertTrue(payload == original)

    def test_foreign_changed_or_missing_donor_never_modifies_target(self):
        payload = archived(202, 4096)
        donor = archived(221, 4103)
        before = copy.deepcopy(payload)
        for invalid in ({**donor, 'source_origin': 'https://shop.mv-centr.ru'},
                        {**donor, 'lesson_title': 'Супервизия 12 - 23.05.24'},
                        {**donor, 'ape': {'name': 'page'}}):
            with (patch.object(Path, 'rglob', return_value=[Path('donor')]),
                  patch.object(Path, 'read_text', return_value=json.dumps({'payload': invalid})),
                  self.assertRaisesRegex(Review, 'donor_changed')):
                normalize_supervision_media(payload, ARCHIVE)
        with patch.object(Path, 'rglob', return_value=[]), self.assertRaisesRegex(Review, 'donor_missing'):
            normalize_supervision_media(payload, ARCHIVE)
        self.assertTrue(payload == before)


if __name__ == '__main__':
    unittest.main()

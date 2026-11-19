import copy
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from import_capture import ARCHIVE, Review, plan_import
import normalize_reviewed_pairs as reviewed


def donor(course, lesson, suffix):
    fields = {
        'videoProvider': 'youtube', 'videoProvider2': 'rutube',
        'videoSrc': 'https://youtu.be/' + 'a' * 11,
        'videoSrc2': 'https://rutube.ru/video/' + suffix * 32 + '/',
    }
    root = {'name': 'page', 'children': [
        {'name': 'header', 'fields': {'html': '<strong>Lesson title</strong>'}},
        {'name': 'video', 'fields': fields},
    ]}
    payload = {'account': 'iomp', 'source_origin': 'https://shop.iomp.ru', 'format': 'ape',
               'course_id': course, 'lesson_id': lesson, 'ape': root}
    return (course, lesson, reviewed._digest(root), (1,)), {'payload': payload}


class ReviewedPairsTests(unittest.TestCase):
    def test_missing_wrong_account_or_modified_donor_is_rejected(self):
        archive, path = Path('archive'), Path('lesson.json')
        entry, original = donor(1, 2, 'a')
        with (patch.object(reviewed, 'DONORS', (entry,)),
              patch.object(Path, 'rglob', return_value=[path]) as find,
              patch.object(Path, 'read_text', return_value=json.dumps(original)) as read):
            self.assertEqual(len(reviewed._donor_pairs(archive)), 1)
            for edit in ('account', 'heading'):
                changed = copy.deepcopy(original)
                if edit == 'account':
                    changed['payload']['account'] = 'other'
                else:
                    changed['payload']['ape']['children'][0]['fields']['html'] += 'changed'
                read.return_value = json.dumps(changed)
                with self.assertRaisesRegex(Review, 'reviewed_pair_donor_changed'):
                    reviewed._donor_pairs(archive)
            find.return_value = []
            with self.assertRaisesRegex(Review, 'reviewed_pair_donor_missing'):
                reviewed._donor_pairs(archive)

    def test_disagreeing_donors_block_the_operation(self):
        first, second = donor(1, 2, 'a'), donor(3, 4, 'b')
        with (patch.object(reviewed, 'DONORS', (first[0], second[0])),
              patch.object(Path, 'rglob', return_value=[Path('lesson.json')]),
              patch.object(Path, 'read_text', side_effect=[json.dumps(first[1]), json.dumps(second[1])])):
            with self.assertRaisesRegex(Review, 'reviewed_pair_donor_conflict'):
                reviewed._donor_pairs(Path('archive'))

    def test_changed_target_and_unrelated_lessons_are_left_intact(self):
        sample = {'account': 'iomp', 'source_origin': 'https://shop.iomp.ru', 'format': 'ape',
                  'course_id': '146', 'lesson_id': '2249', 'ape': {'name': 'page'}}
        before = copy.deepcopy(sample)
        with self.assertRaisesRegex(Review, 'reviewed_pair_source_changed'):
            reviewed.normalize_reviewed_pairs(sample, None)
        self.assertEqual(sample, before)
        sample['lesson_id'] = '2250'
        before = copy.deepcopy(sample)
        reviewed.normalize_reviewed_pairs(sample, None)
        self.assertEqual(sample, before)

    def test_real_capture_preserves_all_videos_and_headings_in_order(self):
        for course, lesson in [('146', '2249'), ('332', '6154')]:
            with self.subTest(course=course, lesson=lesson):
                self.check_video_choices(course, lesson)

    def check_video_choices(self, course, lesson):
        targets = sorted((ARCHIVE / f'course-{course}').rglob(f'lesson-{lesson}.json'))
        if not targets:
            self.skipTest('private capture unavailable')
        payload = json.loads(targets[-1].read_text(encoding='utf-8'))['payload']
        original = payload['ape']['children']
        reviewed.normalize_reviewed_pairs(payload, ARCHIVE)
        prepared = copy.deepcopy(payload)
        reviewed.normalize_reviewed_pairs(payload, ARCHIVE)
        self.assertEqual(payload, prepared)
        plan = plan_import(payload, {})
        self.assertEqual(plan['issues'], [])
        self.assertEqual([b['type'] for b in plan['blocks']], ['videoChoice', 'paragraph'] * 4 + ['videoChoice'])
        videos = [b['data'] for b in plan['blocks'][::2]]
        self.assertEqual([b['youtube'] for b in videos],
                         [n['children'][0]['children'][1]['fields']['videoSrc'] for n in original[::3]])
        self.assertEqual([b['defaultProvider'] for b in videos], ['youtube'] * 5)
        self.assertEqual(videos[0]['rutube'], '')
        pairs = reviewed._donor_pairs(ARCHIVE)
        for video, heading, source in zip(videos[1:], plan['blocks'][1::2], original[2::3]):
            self.assertEqual(heading['data']['text'], source['fields']['html'])
            self.assertEqual((reviewed._heading(source), video['rutube']), pairs[video['youtube']])

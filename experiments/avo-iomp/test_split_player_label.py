import copy
import json
import unittest

from import_capture import ARCHIVE, plan_import
from normalize_iomp_approved_players import _videos
from normalize_split_player_label import LESSONS, Review, normalize_split_player_label


def source(course, lesson):
    snapshots = sorted((ARCHIVE / f'course-{course}').glob(f'*/lesson-{lesson}.json'))
    if not snapshots:
        raise unittest.SkipTest('private IOMP lesson snapshot unavailable')
    return json.loads(snapshots[-1].read_text(encoding='utf-8'))['payload']


class SourcePlayerTests(unittest.TestCase):
    def assert_original_players(self, payload, pairs, images=None):
        videos = list(_videos(payload['ape']))
        urls = [node['fields']['videoSrc'] for node in videos]
        normalize_split_player_label(payload)
        prepared = copy.deepcopy(payload)
        normalize_split_player_label(payload)
        self.assertEqual(payload, prepared)
        plan = plan_import(payload, images)
        choices = [b['data'] for b in plan['blocks'] if b['type'] == 'videoChoice']
        self.assertEqual(len(choices), pairs)
        self.assertTrue(all([b['youtube'], b['rutube']] == urls[i:i + 2]
                            for i, b in zip(range(0, len(urls), 2), choices)))
        self.assertNotIn('legacy_player_pair_unresolved', plan['issues'])
        return plan

    def test_split_label_pairs_in_all_three_lessons(self):
        for course, lesson in LESSONS:
            with self.subTest(lesson=lesson):
                self.assert_original_players(source(course, lesson), 2)

    def test_all_five_shared_posters_stay_above_source_video(self):
        key = 'iomp-223-pair-poster'
        for lesson in range(3840, 3845):
            with self.subTest(lesson=lesson):
                payload = source(223, lesson)
                original = list(_videos(payload['ape']))[0]['fields']['posterSrc']
                plan = self.assert_original_players(payload, 1, {key: '/private/files/retained-poster.jpg'})
                self.assertEqual(payload['ape']['children'][2]['children'][0]['children'][0]['fields']['imageSrc'], original)
                self.assertEqual([b['type'] for b in plan['blocks']][:2], ['image', 'videoChoice'])
                self.assertNotIn('unsupported_video_settings', plan['issues'])

    def test_changed_poster_stops_before_altering_the_pair(self):
        payload = source(223, 3840)
        list(_videos(payload['ape']))[1]['fields']['posterSrc'] = 'https://example.test/different.jpg'
        before = copy.deepcopy(payload)
        with self.assertRaisesRegex(Review, 'poster_changed'):
            normalize_split_player_label(payload)
        self.assertEqual(payload, before)

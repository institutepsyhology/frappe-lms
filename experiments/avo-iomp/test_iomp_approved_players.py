import copy
import hashlib
import json
import unittest
from unittest.mock import patch

from import_capture import ARCHIVE, Review
import normalize_iomp_approved_players as players


def sample(course, lesson, *nodes):
    return {'account': 'iomp', 'source_origin': players.ORIGIN, 'format': 'ape',
            'lesson_id': lesson, 'course_id': course, 'ape': {'name': 'page', 'children': list(nodes)}}


class ApprovedPlayerTests(unittest.TestCase):
    def test_donor_must_match_primary_and_reviewed_alternative(self):
        youtube = 'https://youtu.be/aaaaaaaaaaa'
        url = 'https://rutube.ru/video/' + 'b' * 32 + '/'
        target = sample(249, 4478,
                        {'name': 'video', 'fields': {'videoProvider': 'youtube', 'videoSrc': youtube}},
                        {'name': 'video', 'fields': {'videoProvider': 'rutube', 'videoSrc': youtube}})
        donor = [{'videoProvider': 'youtube', 'videoSrc': youtube, 'videoProvider2': 'rutube', 'videoSrc2': url}]
        original = copy.deepcopy(target)
        with patch.object(players, '_read_donor', return_value=donor):
            with self.assertRaisesRegex(Review, 'donor_changed'):
                players.normalize_approved_players(target, None)
            self.assertEqual(target, original)
            with patch.dict(players.DONORS, {('249', '4478'): (137, 2149, hashlib.sha256(url.encode()).hexdigest())}):
                donor[0]['videoSrc'] = 'https://youtu.be/ccccccccccc'
                with self.assertRaisesRegex(Review, 'donor_mismatch'):
                    players.normalize_approved_players(target, None)
                self.assertEqual(target, original)
                donor[0]['videoSrc'] = youtube
                players.normalize_approved_players(target, None)
                self.assertEqual(target['ape']['children'][1]['fields']['videoSrc'], url)

    def test_unreviewed_visibility_and_other_schools_are_preserved(self):
        video = {'name': 'video', 'fields': {'visibleConditions': {'different': True}, 'videoProvider': 'html5'}}
        payload = sample(321, 5934, video)
        before = copy.deepcopy(payload)
        with self.assertRaisesRegex(Review, 'conditioned_players_changed'):
            players.normalize_approved_players(payload, None)
        self.assertEqual(payload, before)
        payload['account'] = 'mastervision'
        players.normalize_approved_players(payload, None)
        self.assertEqual(payload['ape'], before['ape'])

    def test_reviewed_snapshots_keep_the_exact_other_material_and_are_repeatable(self):
        # Hashes cover all authored fields, retained content and sequence.
        examples = [
            (278, 5520, '9a6fca63f055b37ed2e2a51f2d8f8ad58334c34b526e5bf9bf699ce80a96e721'),
            (321, 5934, 'b710142313390b6c0a30f312aa58bf5570a7dc0e0aeb21c46bc9a826e39ddbed'),
            (321, 5889, '44833d0236be2517728a56fb440ab6531a8819f58d9edb6900c0aad646d27750'),
            (219, 3727, '5b599892b79cb73fdd0850902fad6073ae1dac84ba819ba60ffd4b7910c2ae73'),
            (335, 6329, '5b599892b79cb73fdd0850902fad6073ae1dac84ba819ba60ffd4b7910c2ae73'),
            (249, 4478, 'd4cb47bf8a89afbcd585b4aec55e3b934b1061ed878fa21fed8d6b0f14cd034d'),
        ]
        for course, lesson, expected in examples:
            with self.subTest(course=course, lesson=lesson):
                snapshots = sorted((ARCHIVE / f'course-{course}').glob(f'*/lesson-{lesson}.json'))
                if not snapshots:
                    self.skipTest('private IOMP snapshots unavailable')
                payload = json.loads(snapshots[-1].read_text(encoding='utf-8'))['payload']
                players.normalize_approved_players(payload, ARCHIVE)
                self.assertEqual(players._digest(payload['ape']), expected)
                players.normalize_approved_players(payload, ARCHIVE)
                self.assertEqual(players._digest(payload['ape']), expected)

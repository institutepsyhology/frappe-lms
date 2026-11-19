import copy
import json
import unittest

from import_capture import ARCHIVE, Review, plan_import
from normalize_expired_countdown import FINAL_TEXT, LESSONS, normalize_expired_countdown


class ExpiredCountdownTests(unittest.TestCase):
    def test_time_setting_date_and_scope_are_checked_without_altering_other_lessons(self):
        payload = {'account': 'iomp', 'source_origin': 'https://shop.iomp.ru', 'format': 'ape',
                   'course_id': '233', 'lesson_id': '4298', 'ape': {'children': [
                       {'id': 'timer', 'name': 'timer', 'fields': {'finishDateTime': '2027-06-10'}}]}}
        before = copy.deepcopy(payload)
        with self.assertRaisesRegex(Review, 'expired_countdown_changed'):
            normalize_expired_countdown(payload)
        self.assertEqual(payload, before)
        for override in ({'account': 'mastervision'}, {'lesson_id': 'other'}, {'course_id': 232}):
            another = {**payload, **override}
            normalize_expired_countdown(another)
            self.assertEqual(another['ape'], before['ape'])

    def test_only_countdown_replaced_in_the_private_snapshots(self):
        for cid, lid in sorted(LESSONS):
            with self.subTest(lesson=lid):
                paths = sorted((ARCHIVE / f'course-{cid}').rglob(f'lesson-{lid}.json'))
                if not paths:
                    self.skipTest('private capture unavailable')
                payload = json.loads(paths[-1].read_text(encoding='utf-8'))['payload']
                original = copy.deepcopy(payload)
                normalize_expired_countdown(payload)
                normalize_expired_countdown(payload)
                plan = plan_import(payload, {})
                self.assertEqual(plan['issues'], [])
                self.assertIn(FINAL_TEXT, json.dumps(plan['blocks'], ensure_ascii=False))
                before = original['ape']['children']
                i = next(i for i, node in enumerate(before) if node['name'] == 'timer')
                after = payload['ape']['children']
                self.assertEqual(after[i]['id'], before[i]['id'])
                self.assertEqual(after[i]['name'], 'text')
                after[i] = before[i]
                self.assertTrue(payload == original)

from collections import Counter
import json
from pathlib import Path
import unittest
from unittest.mock import patch

import audit_missing_rutube as audit


class AuditMissingRutubeTests(unittest.TestCase):
    def test_adjacent_players_without_authored_pair_labels_stay_separate(self):
        youtube = 'https://youtu.be/' + 'a' * 11
        rutube = 'https://rutube.ru/video/' + '1' * 32 + '/'
        a = {'name': 'video', 'fields': {'videoProvider': 'youtube', 'videoSrc': youtube}}
        b = {'name': 'video', 'fields': {'videoProvider': 'rutube', 'videoSrc': rutube}}
        payload = {'format': 'ape', 'ape': {'name': 'page', 'children': [a, b]}}
        self.assertEqual(list(audit.source_videos(payload)), [
            {'youtube': youtube, 'rutube': ''}, {'youtube': '', 'rutube': rutube}])
        b['fields'].update(videoProvider2='youtube', videoSrc2=youtube)
        self.assertEqual(list(audit.source_videos(payload))[1], {'youtube': youtube, 'rutube': rutube})

    def test_latest_complete_and_later_lesson_refresh_with_owner_exclusion(self):
        archive = Path('archive')
        folder = archive / 'course-172'
        ids = [20, 2881, 2882]
        status = dict(account='iomp', course_id=172, lesson_ids=ids, saved=ids,
                      issues=[], outline_verified=True)
        base = folder / '2026-11-18'
        newest = folder / '2026-11-19'
        refresh = folder / 'refreshed' / '2026-11-20'
        old = folder / 'refreshed' / '2026-11-17'
        paths = {
            'course-*': [folder],
            '*/capture-status.json': [base / 'capture-status.json', newest / 'capture-status.json'],
            '*/refresh-status.json': [old / 'refresh-status.json', refresh / 'refresh-status.json'],
        }
        documents = {
            base / 'capture-status.json': status,
            newest / 'capture-status.json': {**status, 'saved': ids[:1]},
            base / 'course.json': dict(course_id=172, lesson_ids=ids, title='test'),
            refresh / 'refresh-status.json': dict(account='iomp', course_id=172, lesson_ids=ids, refreshed=[2881]),
        }
        for source, lesson in ((refresh, 2881), (base, 2882)):
            documents[source / f'lesson-{lesson}.json'] = {'payload': dict(
                account='iomp', source_origin=audit.ORIGIN, course_id=172, lesson_id=lesson, course_title='test')}
        with (patch.object(Path, 'glob', autospec=True, side_effect=lambda _, pattern: paths[pattern]),
              patch.object(Path, 'read_text', autospec=True, side_effect=lambda p, **_: json.dumps(documents[p]))):
            counts = Counter()
            records = list(audit.snapshots(archive, counts, []))
        self.assertEqual([lesson for _, lesson, _ in records], [2881, 2882])
        self.assertEqual((counts['courses'], counts['refreshed'], counts['excluded']), (1, 1, 1))

    def test_normalized_ids_reverse_order_and_different_access(self):
        youtube = 'https://youtu.be/' + 'a' * 11
        other_form = 'https://www.youtube.com/watch?v=' + 'a' * 11
        rutube = 'https://rutube.ru/video/' + '1' * 32 + '/'
        different = 'https://rutube.ru/play/embed/' + '2' * 32 + '/'

        def plan(payload, _):
            return {'blocks': [{'type': 'videoChoice', 'data': {'youtube': yt, 'rutube': ru}}
                               for yt, ru in payload['fixture']]}

        with patch.object(audit, 'plan_import', side_effect=plan):
            records = [(1, 2, {'format': 'preview', 'fixture': [(youtube, '')]}),
                       (2, 3, {'format': 'preview', 'fixture': [(other_form, rutube), (youtube, rutube + '?p=fixture')]})]
            singles, donors = audit.index_videos(records, Counter())
            matches, stats = audit.group_matches(singles, donors)
            self.assertEqual(stats['варианты доступа'], 1)
            self.assertEqual(len(matches[(1, 2)][0][2]), 2)
            records.append((3, 4, {'format': 'preview', 'fixture': [(youtube, different)]}))
            singles, donors = audit.index_videos(reversed(records), Counter())
            matches, stats = audit.group_matches(singles, donors)
            self.assertEqual(stats['разные ролики'], 1)
            self.assertEqual(len(matches[(1, 2)][0][2]), 3)

    def test_known_source_blocks_before_repairs(self):
        records = []
        for course, lesson in ((146, 2249), (163, 2667), (211, 3590), (172, 2882), (116, 1886)):
            files = sorted((audit.ARCHIVE / f'course-{course}').glob(f'*/lesson-{lesson}.json'))
            if not files:
                self.skipTest('private archive unavailable')
            records.append((course, lesson, json.loads(files[-1].read_text(encoding='utf-8'))['payload']))
        singles, donors = audit.index_videos(records, Counter())
        matches, stats = audit.group_matches(singles, donors)
        self.assertEqual(sorted(v for v, _, _ in matches[(146, 2249)]), [2, 3, 4, 5])
        self.assertEqual(sorted(v for v, _, _ in matches[(172, 2882)]), [1, 2])
        self.assertEqual(stats['одна пара'], 6)

import unittest
from unittest.mock import Mock, patch

import repair_course335_order as repairer


def runner(initial):
    importer = Mock()
    ids = list(initial)
    rows = {i: {'name': f'doc-{i}', 'chapter': 'one'} for i in repairer.TEMPORARY}
    importer.outline.side_effect = lambda _: {'ids': list(ids), 'course': 'course',
                                               'by_id': {i: rows[i] for i in ids}}
    importer.preview.return_value = ({'action': 'already_imported'}, [])

    def append(staged, apply, images_for_lesson):
        new = [p['lesson_id'] for p in staged if p['lesson_id'] not in ids]
        if apply:
            ids.extend(new)
        return {'created_lesson_ids': new if apply else []}

    def move(method, params):
        assert method == 'tools/call' and params['arguments'] == {
            'method': repairer.MOVE, 'args': {'lesson': 'doc-6311', 'sourceChapter': 'one',
                                             'targetChapter': 'one', 'idx': 2}}
        ids.remove('6311')
        ids.insert(2, '6311')
        return {}

    importer.import_course.side_effect = append
    importer.client.rpc.side_effect = move
    return importer, ids


@patch.object(repairer, 'lesson_images', return_value={})
class RecoveryTests(unittest.TestCase):
    payloads = [{'account': 'iomp', 'course_id': '335', 'lesson_id': lid} for lid in repairer.SOURCE_PREFIX]

    def test_preview_and_every_recovery_state(self, _images):
        for count in range(1, 4):
            with self.subTest(length=count):
                initial = repairer.TEMPORARY[:count]
                importer, ids = runner(initial)
                self.assertEqual(repairer.repair(importer, self.payloads)['status'], 'ready')
                self.assertEqual(ids, initial)
                importer.client.rpc.assert_not_called()
                self.assertEqual(repairer.repair(importer, self.payloads, apply=True)['status'], 'ordered')
                self.assertEqual(ids, repairer.SOURCE_PREFIX)
                self.assertEqual(repairer.repair(importer, self.payloads, apply=True)['status'], 'already_ordered')
                self.assertEqual(importer.client.rpc.call_count, 1)

    def test_unexpected_order_is_rejected_before_write(self, _images):
        importer, _ = runner(['6309', '6311'])
        with self.assertRaisesRegex(repairer.Review, 'unexpected_order'):
            repairer.repair(importer, self.payloads, apply=True)
        importer.import_course.assert_not_called()
        importer.client.rpc.assert_not_called()

    def test_missed_move_is_detected_by_readback(self, _images):
        importer, ids = runner(repairer.TEMPORARY)
        importer.client.rpc.side_effect = None
        importer.client.rpc.return_value = {}
        with self.assertRaisesRegex(repairer.Stop, 'move_uncertain'):
            repairer.repair(importer, self.payloads, apply=True)
        self.assertEqual(ids, repairer.TEMPORARY)

"""Offline controller regressions: fake transport, archive and MCP; no credentials."""
import copy
import unittest
from unittest.mock import patch

import importer
import assets
import settings
import run as mod
import source


class FakeCursor:
    def __init__(self, rows): self.rows = rows
    def fetchall(self): return self.rows
    def __iter__(self): return iter(self.rows)


class FakeDB:
    def __init__(self, store): self.store = store
    def execute(self, sql, parameters=()):
        if sql == "SELECT id FROM courses WHERE state='review'":
            return FakeCursor([(cid,) for cid in self.store.review_ids])
        if sql == 'SELECT id,title FROM courses ORDER BY id':
            return FakeCursor(self.store.catalog_rows)
        if sql != 'SELECT stage FROM errors WHERE consecutive>=?':
            raise AssertionError('unexpected controller SQL')
        return FakeCursor([(stage,) for stage, count in self.store.errors.items() if count >= parameters[0]])


class FakeStore:
    def __init__(self, errors=None):
        self.errors = dict(errors or {})
        self.db = FakeDB(self)
        self.events, self.marks, self.captures, self.completed = [], [], [], []
        self.catalog_rows, self.bound, self.checkpoints = [], [], {}
        self.review_ids = set()
        self.reports = 0
        self.closed = False

    def __enter__(self): return self
    def __exit__(self, *_): self.closed = True
    def error(self, stage, failed):
        self.errors[stage] = self.errors.get(stage, 0) + 1 if failed else 0
        return self.errors[stage]
    def event(self, *values): self.events.append(copy.deepcopy(values))
    def mark(self, course, state): self.marks.append((course, state))
    def capture(self, *values):
        self.captures.append(copy.deepcopy(values))
        return 'synthetic-source-digest'
    def course(self, *values): self.completed.append(copy.deepcopy(values))
    def bind_course(self, course, digest, lesson_digests):
        self.bound.append((course, digest, copy.deepcopy(lesson_digests)))
        self.completed.append((course, [lid for lid, _ in lesson_digests], digest))
    def completed_course(self, course):
        if course not in self.checkpoints:
            raise mod.StorageError('completed_course_checkpoint_missing')
        return copy.deepcopy(self.checkpoints[course])
    def latest(self, *_): raise AssertionError('stored import must use a completed checkpoint, never latest')
    def stable_lesson(self, course_id, lesson_id, parsed): return parsed
    def summary(self): return {'review': len([mark for mark in self.marks if mark[1] == 'review'])}
    def report(self): self.reports += 1


class FakeTransport:
    def __init__(self, replies=()):
        self.replies, self.urls, self.closed = list(replies), [], False
        self.entered = False
    def __enter__(self):
        self.entered = True
        return self
    def __exit__(self, *_): self.closed = True
    def get(self, url):
        self.urls.append(url)
        if not url.startswith(mod.ORIGIN + '/'):
            raise mod.Stop('wrong_source_origin')
        if self.replies:
            result = self.replies.pop(0)
            if isinstance(result, Exception): raise result
            return result
        return '<html>PRIVATE SYNTHETIC SOURCE</html>'


class FakeClient:
    def __init__(self): self.closed = False
    def close(self): self.closed = True


class FakeAssets:
    def __init__(self): self.closed = False
    def lesson_images(self, payload): return {}
    def close(self): self.closed = True


class FakeImporter:
    def __init__(self, behavior):
        self.behavior, self.calls = behavior, []
    def import_course(self, payloads, apply=False, images_for_lesson=None, progress_callback=None):
        cid = payloads[0]['course_id']
        self.calls.append((cid, apply))
        error = self.behavior(cid)
        if error: raise error
        return {'status': 'imported' if apply else 'ready', 'warnings': [], 'created_lesson_ids': []}


def payload(course):
    return {'account': mod.ACCOUNT, 'source_origin': mod.ORIGIN, 'course_id': course,
            'lesson_id': course * 10, 'course_title': 'Synthetic course', 'lesson_title': 'Synthetic lesson',
            'format': 'ape', 'ape': {'name': 'page', 'fields': {}, 'children': []}}


def course_snapshot(ids=(10,), title='Synthetic course'):
    return {'course_id': 1, 'title': title, 'lesson_ids': list(ids),
            'lessons': [{'id': ident, 'title': f'Lesson {ident}', 'raw': {'hidden': 0}} for ident in ids],
            'settings': [{'attrs': {'name': 'TrainingForm[closed]'}, 'value': '0'}],
            'tree': [{'id_training_lessons': ident, 'hidden': 0} for ident in ids], 'cover_url': None}


class ControllerTests(unittest.TestCase):
    def test_unknown_write_cause_is_fixed_metadata_in_status_and_journal(self):
        error = importer.Stop('write_result_uncertain')
        error.reason = 'mcp_connection_failed'
        result = self.invoke(2, importing=lambda cid: error, args=['--apply'])
        self.assertEqual(result[0], 1)
        self.assertEqual(result[5][-1], {'status': 'stopped', 'code': 'write_result_uncertain', 'reason': 'mcp_connection_failed'})
        self.assertIn(('import', None, None, 'stopped', ['write_result_uncertain', 'mcp_connection_failed']), result[1].events)
        error.reason = 'PRIVATE cookie or source'
        result = self.invoke(2, importing=lambda cid: error, args=['--apply'])
        self.assertNotIn('PRIVATE', repr(result[5]) + repr(result[1].events))

    def invoke(self, count, *, collect=None, importing=None, args=(), errors=None, review_ids=()):
        store, transport, client = FakeStore(errors), FakeTransport(), FakeClient()
        store.review_ids = set(review_ids)
        target = FakeImporter(importing or (lambda cid: None))
        output, collected = [], []

        def collecting(archive, reader, cid):
            collected.append(cid)
            reader.get(mod.ORIGIN + source.COURSE + '?id=' + str(cid))
            error = collect(cid) if collect else None
            if error: raise error
            return [payload(cid)]

        rows = [{'id': ident, 'title': f'Synthetic {ident}'} for ident in range(1, count + 1)]
        store.catalog_rows = copy.deepcopy(rows)
        with patch.object(mod, 'Store', return_value=store), patch.object(mod, 'Transport', return_value=transport), \
             patch.object(mod, 'catalog', return_value=rows), patch.object(mod, 'course', side_effect=collecting), \
             patch.object(importer, 'MCPClient', return_value=client) as make_client, \
             patch.object(importer, 'Importer', return_value=target), patch.object(mod, 'emit', side_effect=output.append), \
             patch.object(assets, 'AssetCache', return_value=FakeAssets()), \
             patch.object(settings, 'ensure_private_course', return_value={'status': 'updated'}), \
             patch.object(mod, 'transfer_covers'), \
             patch('sys.argv', ['run.py', *args]):
            status = mod.main()
        return status, store, transport, client, target, output, collected, make_client.call_count

    def test_tenth_consecutive_collection_review_stops_before_course_eleven(self):
        result = self.invoke(12, collect=lambda cid: source.Review('ape_payload_unrecognized'), args=['--collect-only'])
        status, store, transport, _, _, output, collected, clients = result
        self.assertEqual(status, 1)
        self.assertEqual(collected, list(range(1, 11)))
        self.assertEqual(store.errors['collect'], 10)
        self.assertEqual(output[-1], {'status': 'stopped', 'code': 'paused_after_ten_collection_problems'})
        self.assertEqual(store.marks, [(cid, 'review') for cid in range(1, 11)])
        self.assertTrue(store.closed and transport.closed)
        self.assertEqual(clients, 0)

    def test_review_only_skips_imported_courses_and_applies_limit_after_filter(self):
        result = self.invoke(6, review_ids=[2, 4, 6], args=['--review-only', '--collect-only', '--limit', '2'])
        self.assertEqual(result[0], 0)
        self.assertEqual(result[6], [2, 4])

    def test_empty_review_selection_never_opens_target_client(self):
        result = self.invoke(6, args=['--review-only', '--apply'])
        self.assertEqual(result[0], 0)
        self.assertEqual(result[7], 0)
        self.assertEqual(result[5][-1], {'status': 'nothing_to_review'})

    def test_review_selection_cannot_be_mixed_with_cover_only_mode(self):
        with self.assertRaisesRegex(mod.Stop, '^conflicting_mode$'):
            self.invoke(6, args=['--review-only', '--covers-only', '--stored'])

    def test_success_resets_collection_streak_instead_of_counting_all_historical_reviews(self):
        status, store, _, _, _, output, collected, _ = self.invoke(19,
            collect=lambda cid: None if cid == 10 else source.Review('ape_payload_unrecognized'), args=['--collect-only'])
        self.assertEqual(status, 0)
        self.assertEqual(collected, list(range(1, 20)))
        self.assertEqual(store.errors['collect'], 9)
        self.assertEqual(output[-1]['status'], 'finished')

    def test_tenth_consecutive_import_review_stops_before_course_eleven(self):
        result = self.invoke(12, importing=lambda cid: importer.Review('lesson_needs_review'), args=['--apply'])
        status, store, _, client, target, output, collected, _ = result
        self.assertEqual(status, 1)
        self.assertEqual([cid for cid, _ in target.calls], list(range(1, 11)))
        self.assertEqual(collected, list(range(1, 11)))
        self.assertEqual(store.errors['import'], 10)
        self.assertEqual(output[-1], {'status': 'stopped', 'code': 'paused_after_ten_import_problems'})
        self.assertTrue(client.closed)

    def test_success_resets_import_streak(self):
        result = self.invoke(19, importing=lambda cid: None if cid == 10 else importer.Review('lesson_needs_review'), args=['--apply'])
        status, store, _, client, target, output, _, _ = result
        self.assertEqual(status, 0)
        self.assertEqual(len(target.calls), 19)
        self.assertEqual(store.errors['import'], 9)
        self.assertEqual(output[-1]['status'], 'finished')
        self.assertTrue(client.closed)

    def test_wrong_source_identity_is_fatal_on_first_course(self):
        for code in ('source_identity_mismatch', 'wrong_account_origin', 'course_identity_unconfirmed', 'lesson_identity_unconfirmed', 'source_auth_error'):
            with self.subTest(code=code):
                result = self.invoke(3, collect=lambda cid: source.Review(code), args=['--collect-only'])
                status, _, _, _, _, output, collected, _ = result
                self.assertEqual(status, 1)
                self.assertEqual(collected, [1])
                self.assertEqual(output[-1], {'status': 'stopped', 'code': code})

    def test_transport_identity_error_aborts_without_next_course(self):
        result = self.invoke(3, collect=lambda cid: mod.Stop('wrong_source_origin'), args=['--collect-only'])
        self.assertEqual(result[0], 1)
        self.assertEqual(result[6], [1])
        self.assertEqual(result[5][-1], {'status': 'stopped', 'code': 'wrong_source_origin'})

    def test_uncertain_write_aborts_entire_run_and_closes_client(self):
        result = self.invoke(6, importing=lambda cid: importer.Stop('write_result_unknown') if cid == 3 else None, args=['--apply'])
        status, store, transport, client, target, output, collected, _ = result
        self.assertEqual(status, 1)
        self.assertEqual(collected, [1, 2, 3])
        self.assertEqual(target.calls, [(1, True), (2, True), (3, True)])
        self.assertEqual(output[-1], {'status': 'stopped', 'code': 'write_result_unknown'})
        self.assertNotIn((3, 'imported'), store.marks)
        self.assertTrue(client.closed and transport.closed and store.closed)

    def test_importer_identity_fault_aborts_before_next_course(self):
        for code in ('wrong_frappe_site', 'source_account_mismatch', 'preview_identity_invalid'):
            with self.subTest(code=code):
                result = self.invoke(3, importing=lambda cid: importer.Stop(code), args=['--apply'])
                self.assertEqual(result[0], 1)
                self.assertEqual(result[4].calls, [(1, True)])
                self.assertEqual(result[6], [1])
                self.assertEqual(result[5][-1], {'status': 'stopped', 'code': code})
                self.assertTrue(result[3].closed)

    def test_untrusted_exception_text_never_enters_operator_status(self):
        private = 'PRIVATE SOURCE URL AND COOKIE MUST NOT APPEAR'
        result = self.invoke(3, importing=lambda cid: importer.Stop(private), args=['--apply'])
        self.assertEqual(result[0], 1)
        self.assertEqual(result[6], [1])
        self.assertEqual(result[5][-1], {'status': 'stopped', 'code': 'unexpected_failure'})
        self.assertNotIn(private, repr(result[1].events) + repr(result[5]))

    def test_existing_pause_requires_explicit_resume_and_does_not_create_transport(self):
        result = self.invoke(1, args=['--collect-only'], errors={'collect': 10})
        self.assertEqual(result[0], 1)
        self.assertEqual(result[6], [])
        self.assertFalse(result[2].entered)
        self.assertEqual(result[5][-1], {'status': 'stopped', 'code': 'paused_after_ten_problems'})

    def test_explicit_resume_resets_both_streaks_before_processing(self):
        result = self.invoke(1, args=['--collect-only', '--resume'], errors={'collect': 10, 'import': 10})
        self.assertEqual(result[0], 0)
        self.assertTrue(all(value == 0 for value in result[1].errors.values()))

    def test_resume_resets_cover_and_other_stage_streaks_before_processing(self):
        result = self.invoke(1, args=['--collect-only', '--resume'],
                             errors={stage: 10 for stage in ('collect', 'import', 'cover', 'catalog', 'settings')})
        self.assertEqual(result[0], 0)
        self.assertEqual(result[6], [1])
        self.assertTrue(all(value == 0 for value in result[1].errors.values()))


class CourseRecheckTests(unittest.TestCase):
    def collect(self, before, after):
        store = FakeStore()
        transport = FakeTransport()
        with patch.object(source, 'parse_course', side_effect=[before, after]), \
             patch.object(source, 'parse_lesson', side_effect=lambda html, cid, lid, *_: {'payload': {**payload(cid), 'lesson_id': lid}}):
            try:
                result = mod.course(store, transport, 1)
            except Exception as exc:
                return store, transport, None, exc
        return store, transport, result, None

    def test_stable_course_is_completed_only_after_final_source_recheck(self):
        before = course_snapshot((10, 11))
        store, transport, result, error = self.collect(before, copy.deepcopy(before))
        self.assertIsNone(error)
        self.assertEqual(len(result), 2)
        self.assertEqual(len(transport.urls), 4)
        self.assertEqual(store.completed, [(1, [10, 11], 'synthetic-source-digest')])
        self.assertEqual(store.events[-1], ('collect', 1, None, 'complete'))

    def test_reordered_or_renamed_lessons_never_mark_the_course_complete(self):
        before = course_snapshot((10, 11))
        reordered = course_snapshot((11, 10))
        renamed = copy.deepcopy(before); renamed['lessons'][0]['title'] = 'Changed'
        for after in (reordered, renamed):
            with self.subTest(after=after['lesson_ids']):
                store, _, result, error = self.collect(before, after)
                self.assertIsInstance(error, source.Review)
                self.assertEqual(str(error), 'course_changed_during_collection')
                self.assertIsNone(result)
                self.assertEqual(store.completed, [])
                self.assertEqual(len([row for row in store.captures if row[0] == 'course']), 2)

    def test_recheck_parse_failure_is_archived_before_propagating(self):
        store, _, _, error = self.collect(course_snapshot(), source.Review('course_tree_unrecognized'))
        self.assertIsInstance(error, source.Review)
        self.assertEqual(store.completed, [])
        evidence = [row for row in store.captures if row[0] == 'course']
        self.assertEqual(len(evidence), 2)
        self.assertEqual(evidence[-1][3]['error'], 'course_tree_unrecognized')
        self.assertEqual(evidence[-1][3]['verified'], False)

    def test_changed_course_settings_or_tree_state_require_review(self):
        before = course_snapshot()
        settings_changed = copy.deepcopy(before); settings_changed['settings'][0]['value'] = '1'
        tree_changed = copy.deepcopy(before); tree_changed['tree'][0]['hidden'] = 1
        for after in (settings_changed, tree_changed):
            with self.subTest(changed='settings' if after['settings'] != before['settings'] else 'tree'):
                store, _, result, error = self.collect(before, after)
                self.assertIsInstance(error, source.Review)
                self.assertEqual(str(error), 'course_changed_during_collection')
                self.assertIsNone(result)
                self.assertEqual(store.completed, [])


class StoredCourseTests(unittest.TestCase):
    def test_stored_course_requires_a_completed_source_checkpoint(self):
        store = FakeStore()
        with self.assertRaises(source.Review):
            mod.stored_course(store, 1)

    def test_stored_course_uses_exact_checkpoint_instead_of_latest_snapshots(self):
        store = FakeStore()
        store.checkpoints[1] = [payload(1)]
        self.assertEqual(mod.stored_course(store, 1), [payload(1)])

    def test_stored_checkpoint_corruption_is_fatal_not_a_skipped_review(self):
        store = FakeStore()
        with patch.object(store, 'completed_course', side_effect=mod.StorageError('source_digest_mismatch')):
            with self.assertRaises((mod.Stop, mod.StorageError)):
                mod.stored_course(store, 1)


if __name__ == '__main__':
    unittest.main()

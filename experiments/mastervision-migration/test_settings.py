"""Synthetic privacy-setting MCP checks; never access a site or credentials."""
import copy
import unittest

import settings
from importer import Review, Stop


class Client:
    account, site = 'mastervision', 'my-lk.mastervision.su'

    def __init__(self):
        self.doc = {'doctype': 'LMS Course', 'name': 'synthetic-course', 'published': 0,
            'custom_avo_account': 'mastervision', 'custom_avo_id': '618', 'custom_lms_id': '618',
            'disable_self_learning': 0, 'image': '/files/owned-cover.png',
            'title': 'PRIVATE TITLE', 'description': '<p>PRIVATE SOURCE CONTENT</p>',
            'modified': '2026-11-13 01:00:00.000000', 'modified_by': 'Administrator',
            'chapters': [{'chapter': 'chapter-1', 'idx': 1, 'modified': 'old', 'modified_by': 'Administrator'}],
            'instructors': [{'instructor': 'PRIVATE INSTRUCTOR', 'idx': 1, 'modified': 'old'}]}
        self.calls, self.writes = [], []
        self.duplicate = self.missing = False
        self.write_fails = self.invalid_write_response = self.readback_fails = False
        self.race = False
        self.change = None
        self.bad_final = None

    def call(self, tool, arguments):
        self.calls.append((tool, copy.deepcopy(arguments)))
        if tool == 'list_documents':
            assert arguments['doctype'] == 'LMS Course'
            assert arguments['filters'] == [['custom_avo_account', '=', 'mastervision'], ['custom_avo_id', '=', '618']]
            rows = [] if self.missing else [self.doc] * (2 if self.duplicate else 1)
            return {'documents': copy.deepcopy(rows), 'has_next_page': False}
        assert tool == 'get_document' and arguments == {'doctype': 'LMS Course', 'name': 'synthetic-course'}
        if self.writes and self.readback_fails:
            raise RuntimeError('PRIVATE AUTHENTICATION OR CONTENT IN EXCEPTION')
        value = copy.deepcopy(self.doc)
        if self.writes and self.bad_final: self.bad_final(value)
        return value

    def rpc(self, method, params):
        self.writes.append((method, copy.deepcopy(params)))
        assert method == 'tools/call' and params['name'] == 'update_document'
        args = params['arguments']
        assert set(args) == {'doctype', 'name', 'data'}
        assert (args['doctype'], args['name']) == ('LMS Course', 'synthetic-course')
        assert args['data'] == {'disable_self_learning': 1, 'modified': '2026-11-13 01:00:00.000000'}
        if self.race:
            self.doc['image'] = '/files/manually-changed.png'
            self.doc['modified'] = '2026-11-13 01:00:01.000000'
        if args['data']['modified'] != self.doc['modified']:
            return {'isError': True, 'content': [{'text': 'PRIVATE TIMESTAMP DETAILS'}]}
        self.doc['disable_self_learning'] = 1
        self.doc['modified'] = '2026-11-13 01:00:02.000000'
        for row in self.doc['chapters'] + self.doc['instructors']: row['modified'] = self.doc['modified']
        if self.change: self.change(self.doc)
        if self.write_fails: raise RuntimeError('PRIVATE SOURCE after possible commit')
        if self.invalid_write_response: return {'content': [{'text': 'PRIVATE SOURCE'}]}
        return {'structuredContent': copy.deepcopy(self.doc)}


class PrivateSettingsTests(unittest.TestCase):
    def test_wrong_site_and_account_rejected_before_any_target_request(self):
        for key, value in [('site', 'my-lk.mv-centr.ru'), ('site', 'my-lk.iomp.ru'), ('account', 'mv-centr')]:
            client = Client(); setattr(client, key, value)
            with self.subTest(key=key, value=value), self.assertRaisesRegex(Stop, '^wrong_frappe_site$'):
                settings.ensure_private_course(client, 618, apply=True)
            self.assertEqual(client.calls + client.writes, [])

    def test_missing_duplicate_published_and_foreign_course_never_write(self):
        for key, value in [('missing', True), ('duplicate', True), ('published', 1),
                           ('custom_avo_id', '619'), ('custom_lms_id', '619'), ('custom_avo_account', 'mv-centr')]:
            client = Client()
            if key in ('missing', 'duplicate'): setattr(client, key, value)
            else: client.doc[key] = value
            with self.subTest(key=key), self.assertRaises((Review, Stop)):
                settings.ensure_private_course(client, 618, apply=True)
            self.assertEqual(client.writes, [])

    def test_unusual_boolean_values_are_reviewed_instead_of_coerced(self):
        for value in (None, True, '0', 2, {}, []):
            client = Client(); client.doc['disable_self_learning'] = value
            with self.subTest(value=value), self.assertRaisesRegex(Review, '^private_settings_value_invalid$'):
                settings.ensure_private_course(client, 618, apply=True)
            self.assertEqual(client.writes, [])

    def test_dry_run_does_not_change_anything_and_exposes_only_id_status(self):
        client = Client(); before = copy.deepcopy(client.doc)
        self.assertEqual(settings.ensure_private_course(client, '618'), {'course_id': '618', 'status': 'ready'})
        self.assertEqual(client.doc, before)
        self.assertEqual(client.writes, [])

    def test_already_private_is_idempotent_and_does_not_write(self):
        client = Client(); client.doc['disable_self_learning'] = 1
        self.assertEqual(settings.ensure_private_course(client, 618, apply=True), {'course_id': '618', 'status': 'already_private'})
        self.assertEqual(client.writes, [])

    def test_update_changes_only_toggle_and_expected_timestamps(self):
        client = Client(); before = settings._protected(client.doc)
        result = settings.ensure_private_course(client, 618, apply=True)
        self.assertEqual(result, {'course_id': '618', 'status': 'updated'})
        self.assertEqual(client.doc['disable_self_learning'], 1)
        self.assertEqual(client.doc['published'], 0)
        self.assertEqual(settings._protected(client.doc), before)
        self.assertEqual(len(client.writes), 1)
        self.assertTrue(all(args['doctype'] == 'LMS Course' for _, args in client.calls))

    def test_repeated_apply_does_not_issue_another_update(self):
        client = Client()
        settings.ensure_private_course(client, 618, apply=True)
        result = settings.ensure_private_course(client, 618, apply=True)
        self.assertEqual(result['status'], 'already_private')
        self.assertEqual(len(client.writes), 1)

    def test_optimistic_timestamp_race_never_clobbers_manual_change(self):
        client = Client(); client.race = True
        with self.assertRaisesRegex(Stop, '^private_settings_write_uncertain$'):
            settings.ensure_private_course(client, 618, apply=True)
        self.assertEqual(client.doc['disable_self_learning'], 0)
        self.assertEqual(client.doc['image'], '/files/manually-changed.png')
        self.assertEqual(len(client.writes), 1)

    def test_unknown_write_and_missing_structured_result_stop_without_retry(self):
        for flag in ('write_fails', 'invalid_write_response'):
            client = Client(); setattr(client, flag, True)
            with self.subTest(flag=flag), self.assertRaisesRegex(Stop, '^private_settings_write_uncertain$'):
                settings.ensure_private_course(client, 618, apply=True)
            self.assertEqual(len(client.writes), 1)
            self.assertEqual(client.doc['disable_self_learning'], 1)  # Possible commit is preserved.

    def test_unknown_post_update_readback_stops_without_retry(self):
        client = Client(); client.readback_fails = True
        with self.assertRaisesRegex(Stop, '^private_settings_readback_uncertain$'):
            settings.ensure_private_course(client, 618, apply=True)
        self.assertEqual(len(client.writes), 1)

    def test_content_image_and_child_reference_changes_are_all_detected(self):
        for field in ('description', 'image', 'chapters'):
            client = Client()
            client.change = lambda doc, key=field: doc.__setitem__(key, [] if key == 'chapters' else 'UNEXPECTED')
            with self.subTest(field=field), self.assertRaisesRegex(Stop, '^private_settings_readback_mismatch$'):
                settings.ensure_private_course(client, 618, apply=True)
            self.assertEqual(len(client.writes), 1)

    def test_final_readback_cannot_hide_lost_toggle_or_changed_numeric_id(self):
        for field, value in [('disable_self_learning', 0), ('custom_lms_id', '999'), ('published', 1)]:
            client = Client(); client.bad_final = lambda doc, key=field, new=value: doc.__setitem__(key, new)
            with self.subTest(field=field), self.assertRaises(Stop):
                settings.ensure_private_course(client, 618, apply=True)
            self.assertEqual(len(client.writes), 1)

    def test_invalid_apply_type_never_uses_target(self):
        client = Client()
        with self.assertRaisesRegex(Review, '^private_settings_apply_invalid$'):
            settings.ensure_private_course(client, 618, apply=1)
        self.assertEqual(client.calls + client.writes, [])


if __name__ == '__main__': unittest.main()

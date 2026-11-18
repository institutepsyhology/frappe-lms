import unittest
from unittest.mock import Mock

from import_capture import Stop, verify_empty_destination


class EmptyDestinationTests(unittest.TestCase):
    def test_checks_course_files_and_every_lesson_before_resuming(self):
        client = Mock()
        client.call.return_value = {'documents': [], 'has_next_page': False}
        ids = [str(i + 1) for i in range(120)]
        verify_empty_destination(client, '91', ids)
        queries = [call.args[1] for call in client.call.call_args_list]
        self.assertEqual([q['doctype'] for q in queries], ['LMS Course', 'File', 'File', 'Course Lesson', 'Course Lesson'])
        self.assertEqual([i for q in queries[3:] for i in q['filters']['custom_avo_id'][1]], ids)
        self.assertTrue(all(q['filters']['custom_avo_account'] == 'iomp' for q in [queries[0], *queries[3:]]))

    def test_any_existing_record_or_incomplete_read_requires_reconciliation(self):
        for reply in [{'documents': [{'name': 'existing'}], 'has_next_page': False},
                      {'documents': [], 'has_next_page': True}, {}]:
            with self.subTest(reply=reply):
                client = Mock()
                client.call.side_effect = [{'documents': [], 'has_next_page': False}, reply]
                with self.assertRaisesRegex(Stop, 'course_prior_write_requires_reconciliation'):
                    verify_empty_destination(client, '91', ['1829'])

import io
import json
import unittest
from unittest.mock import Mock

from import_worker import ARCHIVE, serve


def requests(*ids, resume=None):
    rows = [{'course_id': cid, 'directory': str(ARCHIVE / f'course-{cid}' / 'capture')}
            for cid in ids]
    for row in rows:
        if row['course_id'] == resume:
            row['resume_empty'] = True
    return io.BytesIO(b''.join((json.dumps(row, ensure_ascii=False) + '\n').encode() for row in rows))


class WorkerTests(unittest.TestCase):
    def test_one_lazy_connection_until_stopped_and_no_following_course(self):
        outcomes = iter([('1', 'review'), ('2', 'imported'), ('3', 'stopped')])
        connector = Mock()
        seen = []

        def import_one(directory, *, client_scope, require_empty):
            cid, status = next(outcomes)
            self.assertEqual(require_empty, cid == '2')
            if status == 'review':
                connector.assert_not_called()
            else:
                with client_scope() as client:
                    seen.append(client)
                    client.close.assert_not_called()
            return {'status': status, 'course_id': cid}

        output = io.StringIO()
        serve(requests('1', '2', '3', '4', resume='2'), output, connect=connector, import_course=import_one)
        self.assertEqual([json.loads(line)['status'] for line in output.getvalue().splitlines()],
                         ['review', 'imported', 'stopped'])
        self.assertEqual(seen, [connector.return_value, connector.return_value])
        connector.assert_called_once()
        connector.return_value.close.assert_called_once_with()

    def test_empty_batch_and_invalid_request_do_not_connect(self):
        connector, importer, out = Mock(), Mock(), io.StringIO()
        serve(requests(), out, connect=connector, import_course=importer)
        for line in [b'{}\n', b'{"course_id":"2","directory":"course-1/capture"}\n', b'{"course_id":"2"}']:
            with self.assertRaises(ValueError):
                serve(io.BytesIO(line), out, connect=connector, import_course=importer)
        self.assertEqual(out.getvalue(), '')
        importer.assert_not_called()
        connector.assert_not_called()

    def test_uncertain_result_closes_connection_and_never_reads_the_next_course(self):
        connector, out = Mock(), io.StringIO()

        def wrong_course(directory, *, client_scope, require_empty):
            with client_scope():
                return {'status': 'imported', 'course_id': '3'}

        with self.assertRaisesRegex(ValueError, 'invalid_worker_result'):
            serve(requests('1', '2'), out, connect=connector, import_course=wrong_course)
        self.assertEqual(out.getvalue(), '')
        connector.assert_called_once()
        connector.return_value.close.assert_called_once_with()

import importlib.util
import io
import json
import types
import contextlib
import unittest
from pathlib import Path
from unittest.mock import mock_open, patch

spec = importlib.util.spec_from_file_location('avo_user_batch', Path(__file__).with_name('import_mvcentr_users.py'))
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class ImportTest(unittest.TestCase):
    def test_event_contains_only_identifier_and_status(self):
        mock = mock_open()
        with patch('builtins.open', mock), patch.object(module.Path, 'open', mock):
            module.log_event(123, 'unique_conflict')
        record = json.loads(mock().write.call_args.args[0])
        self.assertEqual(record['contact_id'], 123)
        self.assertEqual(record['account'], 'mv-centr')
        self.assertEqual(record['status'], 'unique_conflict')
        self.assertEqual(set(record), {'at', 'contact_id', 'account', 'status'})

    def test_source_identifier_and_no_welcome_mail(self):
        record = {'contact': {'email': 'Test@example.test', 'name': 'Test'},
                  'credentials': {'password': 'sample'}}
        data = module.payload(123, record)
        self.assertEqual(data['custom_avo_contact_id'], '123')
        self.assertEqual(data['custom_avo_account'], 'mv-centr')
        self.assertEqual(data['send_welcome_email'], 0)
        self.assertEqual(data['email'], 'test@example.test')

    def test_missing_or_invalid_email_not_imported(self):
        record = {'contact': {'email': 'invalid'}, 'credentials': {'password': 'sample'}}
        self.assertIsNone(module.payload(123, record))

    def test_readback_requires_all_migrated_fields_to_match(self):
        record = {'contact': {'email':'test@example.test','name':'Test','phone_number':'9999','telegram_user':'sample'},
                  'credentials': {'password':'sample'}}
        data = module.payload(123, record)
        saved = {k:v for k,v in data.items() if k != 'new_password'}
        self.assertTrue(module.saved_matches(saved, data))
        saved['mobile_no'] = '0000'
        self.assertFalse(module.saved_matches(saved, data))
        saved['mobile_no'] = data['mobile_no']
        saved['custom_avo_telegram_username'] = ''
        self.assertFalse(module.saved_matches(saved, data))

    def test_readback_email_is_query_filter_not_path(self):
        from urllib.parse import urlsplit, parse_qs
        url=module.user_readback_url('test/name@example.test')
        self.assertEqual(urlsplit(url).path, '/api/v2/document/User')
        filters=json.loads(parse_qs(urlsplit(url).query)['filters'][0])
        self.assertEqual(filters,[['name','=','test/name@example.test']])

    def test_ten_consecutive_unusable_records_stop_batch(self):
        records = [(i, {'contact': {'email': ''}, 'credentials': {}}) for i in range(1, 12)]
        helper = types.SimpleNamespace(authenticated_headers=lambda site: {})
        loader = types.SimpleNamespace(exec_module=lambda obj: None)
        output = io.StringIO()
        with patch.object(module, 'load', side_effect=lambda: iter(records)), \
             patch.object(module, 'log_event') as log, \
             patch.object(module, 'JOURNAL', types.SimpleNamespace(exists=lambda: False)), \
             patch.object(module.importlib.util, 'spec_from_file_location', return_value=types.SimpleNamespace(loader=loader)), \
             patch.object(module.importlib.util, 'module_from_spec', return_value=helper), \
             patch('sys.argv', ['import', '--apply', '--limit', '10']), contextlib.redirect_stdout(output):
            module.main()
        result = json.loads(output.getvalue())
        self.assertEqual(result['missing_email_or_password'], 10)
        self.assertEqual(result['stopped_consecutive_issues'], 1)
        self.assertEqual(log.call_count, 10)

    def test_timeout_during_write_is_logged_and_stops(self):
        records = [(123, {'contact': {'email': 'test@example.test'}, 'credentials': {'password': 'sample'}})]
        helper = types.SimpleNamespace(authenticated_headers=lambda site: {})
        loader = types.SimpleNamespace(exec_module=lambda obj: None)
        output = io.StringIO()
        with patch.object(module, 'load', side_effect=lambda: iter(records)), \
             patch.object(module, 'log_event') as log, \
             patch.object(module, 'JOURNAL', types.SimpleNamespace(exists=lambda: False)), \
             patch.object(module.importlib.util, 'spec_from_file_location', return_value=types.SimpleNamespace(loader=loader)), \
             patch.object(module.importlib.util, 'module_from_spec', return_value=helper), \
             patch.object(module.DIRECT_OPENER, 'open', side_effect=module.urllib.error.URLError('timed out')), \
             patch('sys.argv', ['import', '--apply']), contextlib.redirect_stdout(output):
            module.main()
        self.assertEqual(json.loads(output.getvalue())['create_error'], 1)
        log.assert_called_once_with(123, 'write_outcome_unknown')

    def test_unresolved_write_stops_before_any_network_request(self):
        entry = json.dumps({'contact_id': 123, 'account': 'mv-centr', 'status': 'write_outcome_unknown'}) + '\n'
        journal = types.SimpleNamespace(exists=lambda: True, open=lambda **kw: io.StringIO(entry))
        output = io.StringIO()
        with patch.object(module, 'load', side_effect=lambda: iter([])), \
             patch.object(module, 'JOURNAL', journal), \
             patch.object(module.DIRECT_OPENER, 'open') as network, \
             patch('sys.argv', ['import', '--apply']), contextlib.redirect_stdout(output):
            module.main()
        self.assertEqual(json.loads(output.getvalue())['unresolved_write_outcomes'], 1)
        network.assert_not_called()

    def test_only_confirmed_throttle_is_retried(self):
        from urllib.error import HTTPError, URLError
        body = json.dumps({'exc_type':'ValidationError','exc':'File user.py, line 1450, in throttle_user_creation'}).encode()
        rejected = HTTPError('https://example.test',417,'error',{},io.BytesIO(body))
        class Response:
            status = 200
            def __enter__(self): return self
            def __exit__(self,*args): pass
        with patch.object(module.DIRECT_OPENER,'open',side_effect=[rejected,Response()]) as send, patch.object(module.time,'sleep') as sleep:
            self.assertEqual(module.create_user('request'),200)
            self.assertEqual(send.call_count,2)
            sleep.assert_called_once_with(60)
        with patch.object(module.DIRECT_OPENER,'open',side_effect=URLError('timeout')) as send, patch.object(module.time,'sleep') as sleep:
            with self.assertRaises(URLError):module.create_user('request')
            self.assertEqual(send.call_count,1)
            sleep.assert_not_called()

    def test_background_reports_errors_and_conflict_only_outcomes(self):
        import sys
        sys.path.insert(0, str(Path(__file__).parent))
        import run_background
        self.assertTrue(run_background.was_stopped({'created': 1, 'create_error': 1}, 0))
        self.assertTrue(run_background.was_stopped({'unresolved_write_outcomes': 1}, 0))
        self.assertTrue(run_background.was_stopped({'created': 1}, 1))
        self.assertFalse(run_background.was_stopped({'created': 1, 'create_error': 2, 'unique_conflict_skipped': 2}, 0))


if __name__ == '__main__':
    unittest.main()

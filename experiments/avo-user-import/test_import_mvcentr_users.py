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

    def test_ten_consecutive_unusable_records_stop_batch(self):
        records = [(i, {'contact': {'email': ''}, 'credentials': {}}) for i in range(1, 12)]
        helper = types.SimpleNamespace(authenticated_headers=lambda site: {})
        loader = types.SimpleNamespace(exec_module=lambda obj: None)
        output = io.StringIO()
        with patch.object(module, 'load', side_effect=lambda: iter(records)), \
             patch.object(module, 'log_event') as log, \
             patch.object(module.importlib.util, 'spec_from_file_location', return_value=types.SimpleNamespace(loader=loader)), \
             patch.object(module.importlib.util, 'module_from_spec', return_value=helper), \
             patch('sys.argv', ['import', '--apply', '--limit', '10']), contextlib.redirect_stdout(output):
            module.main()
        result = json.loads(output.getvalue())
        self.assertEqual(result['missing_email_or_password'], 10)
        self.assertEqual(result['stopped_consecutive_issues'], 1)
        self.assertEqual(log.call_count, 10)


if __name__ == '__main__':
    unittest.main()

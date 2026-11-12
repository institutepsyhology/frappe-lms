"""Network retries are bounded and restricted to proven read-only requests."""
import json
import unittest
from unittest.mock import patch
from urllib.error import HTTPError, URLError

import importer as mod


class Response:
    def __init__(self, ident): self.raw = json.dumps({'id': ident, 'result': {}}).encode()
    def __enter__(self): return self
    def __exit__(self, *_): pass
    def read(self, *_): return self.raw


class RetryTests(unittest.TestCase):
    def client(self, errors):
        client = mod.MCPClient.__new__(mod.MCPClient)
        client.n, client.auth = 0, {'Cookie': 'sid=PRIVATE'}
        calls = []
        class Opener:
            def open(self, request, **_):
                calls.append(json.loads(request.data))
                error = errors.pop(0) if errors else None
                if error: raise error
                return Response(calls[-1]['id'])
        client.opener = Opener()
        return client, calls

    def test_readonly_methods_retry_connection_failure_and_keep_request_identity(self):
        for name, args in [('list_documents', {}), ('get_document', {}),
                           ('call_method', {'method': mod.METHOD, 'args': {'dry_run': True}})]:
            with self.subTest(name=name), patch.object(mod.time, 'sleep') as sleep:
                client, calls = self.client([URLError('PRIVATE error'), None])
                self.assertEqual(client.rpc('tools/call', {'name': name, 'arguments': args}), {})
                self.assertEqual(len(calls), 2)
                self.assertEqual(calls[0], calls[1])
                sleep.assert_called_once_with(1)

    def test_mutations_unknown_calls_and_nonboolean_dry_run_are_never_retried(self):
        for name, args in [('update_document', {}), ('create_document', {}),
                           ('call_method', {'method': mod.METHOD, 'args': {'dry_run': False}}),
                           ('call_method', {'method': mod.METHOD, 'args': {'dry_run': 'true'}}),
                           ('call_method', {'method': 'unknown', 'args': {'dry_run': True}})]:
            with self.subTest(name=name, args=args), patch.object(mod.time, 'sleep') as sleep:
                client, calls = self.client([URLError('PRIVATE source')])
                with self.assertRaisesRegex(mod.Stop, '^mcp_connection_failed$') as raised:
                    client.rpc('tools/call', {'name': name, 'arguments': args})
                self.assertEqual(len(calls), 1)
                self.assertNotIn('PRIVATE', str(raised.exception))
                sleep.assert_not_called()

    def test_read_failure_is_bounded_to_three_attempts(self):
        client, calls = self.client([TimeoutError()] * 4)
        with patch.object(mod.time, 'sleep') as sleep:
            with self.assertRaisesRegex(mod.Stop, '^mcp_connection_failed$'):
                client.rpc('initialize', {})
        self.assertEqual(len(calls), 3)
        self.assertEqual([call.args for call in sleep.call_args_list], [(1,), (2,)])

    def test_auth_redirect_and_permanent_http_errors_are_not_retried(self):
        for code in (301, 401, 403, 404, 413):
            with self.subTest(code=code), patch.object(mod.time, 'sleep') as sleep:
                client, calls = self.client([HTTPError('PRIVATE', code, 'PRIVATE', {}, None)])
                with self.assertRaises(mod.Stop) as raised: client.rpc('initialize', {})
                self.assertNotIn('PRIVATE', str(raised.exception))
                self.assertEqual(len(calls), 1)
                sleep.assert_not_called()

    def test_transient_http_read_error_can_retry_but_write_cannot(self):
        for method, params, expected in [('initialize', {}, 2),
                ('tools/call', {'name': 'update_document', 'arguments': {}}, 1)]:
            with self.subTest(method=method), patch.object(mod.time, 'sleep'):
                client, calls = self.client([HTTPError('PRIVATE', 503, 'PRIVATE', {}, None), None])
                if expected == 2: self.assertEqual(client.rpc(method, params), {})
                else:
                    with self.assertRaises(mod.Stop): client.rpc(method, params)
                self.assertEqual(len(calls), expected)

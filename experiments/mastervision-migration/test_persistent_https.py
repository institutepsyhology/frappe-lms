"""Real HTTPResponse framing with synthetic sockets; no network or credentials."""
import http.client
import io
import unittest
import urllib.error
import urllib.request

import persistent_https as mod


class Socket:
    def __init__(self, wire=b""):
        self.wire, self.timeouts = wire, []

    def makefile(self, *args):
        return io.BytesIO(self.wire)

    def settimeout(self, timeout):
        self.timeouts.append(timeout)


def response(body=b'{"ok":true}', status=200, extra="", length=None):
    length = len(body) if length is None else length
    raw = (f"HTTP/1.1 {status} Synthetic\r\nContent-Length: {length}\r\n{extra}\r\n".encode() + body)
    result = http.client.HTTPResponse(Socket(raw))
    result.begin()
    return result


class Connection:
    def __init__(self, responses):
        self.responses = list(responses)
        self.requests, self.closes, self.sock = [], 0, Socket()

    def request(self, method, selector, body=None, headers=None):
        self.requests.append((method, selector, body, headers))

    def getresponse(self):
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    def close(self):
        self.closes += 1
        self.sock = None


class Factory:
    def __init__(self, *groups):
        self.groups, self.calls, self.connections = list(groups), [], []

    def __call__(self, host, port, **kwargs):
        self.calls.append((host, port, kwargs))
        result = Connection(self.groups.pop(0))
        self.connections.append(result)
        return result


class Tests(unittest.TestCase):
    def opener(self, factory, **kwargs):
        handler = mod.PersistentHTTPS(connection_factory=factory, **kwargs)
        return handler, urllib.request.build_opener(urllib.request.ProxyHandler({}), handler)

    @staticmethod
    def request(url=None):
        return urllib.request.Request(url or mod.ERROR_URL, data=b"{}",
                                      headers={"Content-Type": "application/json", "Cookie": "synthetic"})

    def test_two_fully_read_calls_share_one_connection_and_keep_http_response(self):
        factory = Factory([response(), response()])
        handler, opener = self.opener(factory)
        for _ in range(2):
            with opener.open(self.request(), timeout=60) as result:
                self.assertIsInstance(result, http.client.HTTPResponse)
                self.assertEqual(result.code, 200)
                self.assertEqual(result.geturl(), mod.ERROR_URL)
                self.assertEqual(result.read(32 * 1024 * 1024 + 1), b'{"ok":true}')
        self.assertEqual(len(factory.calls), 1)
        self.assertEqual(factory.calls[0][:2], (mod.SITE, 443))
        self.assertEqual(factory.connections[0].closes, 0)
        request = factory.connections[0].requests[0]
        self.assertEqual(request[:3], ("POST", "/api/v2/mcp", b"{}"))
        self.assertEqual(request[3]["Content-length"], "2")
        self.assertEqual(request[3]["Host"], mod.SITE)
        self.assertFalse(any(k.lower() == "connection" for k in request[3]))
        handler.close()
        self.assertEqual(factory.connections[0].closes, 1)

    def test_exact_path_and_query_preserved(self):
        factory = Factory([response()])
        _, opener = self.opener(factory)
        url = "https://" + mod.SITE + "/api/v2/mcp?x=a%2Fb&empty="
        with opener.open(self.request(url)) as result:
            result.read()
        self.assertEqual(factory.connections[0].requests[0][1], "/api/v2/mcp?x=a%2Fb&empty=")

    def test_wrong_authorities_never_reach_factory(self):
        factory = Factory()
        _, opener = self.opener(factory)
        for url in ("https://my-lk.mv-centr.ru/api/v2/mcp", "http://" + mod.SITE + "/",
                    "https://" + mod.SITE + ":443/", "https://user@" + mod.SITE + "/",
                    "https://" + mod.SITE + ".example/", "https://" + mod.SITE + "/#fragment"):
            with self.subTest(url=url), self.assertRaisesRegex(urllib.error.URLError, "destination_rejected"):
                opener.open(self.request(url))
        self.assertEqual(factory.calls, [])

    def test_host_proxy_and_length_injections_rejected_before_connection(self):
        factory = Factory()
        handler, _ = self.opener(factory)
        for headers in ({"Host": "foreign.example"}, {"Proxy-Authorization": "synthetic"},
                        {"Content-Length": "999"}, {"Transfer-Encoding": "chunked"}):
            req = self.request()
            for key, value in headers.items():
                req.add_header(key, value)
            with self.subTest(headers=headers), self.assertRaisesRegex(urllib.error.URLError, "headers_rejected"):
                handler.https_open(req)
        req = self.request()
        req.set_proxy("proxy.example:123", "http")
        with self.assertRaisesRegex(urllib.error.URLError, "destination_rejected"):
            handler.https_open(req)
        self.assertEqual(factory.calls, [])

    def test_non_200_closes_without_following_location(self):
        factory = Factory([response(status=302, extra="Location: https://foreign.example/\r\n")], [response()])
        _, opener = self.opener(factory)
        with self.assertRaises(urllib.error.HTTPError) as raised:
            opener.open(self.request())
        self.assertEqual(raised.exception.code, 302)
        self.assertEqual(raised.exception.url, mod.ERROR_URL)
        self.assertEqual(factory.connections[0].closes, 1)
        self.assertEqual(len(factory.calls), 1)
        with opener.open(self.request()) as result:
            result.read()
        self.assertEqual(len(factory.calls), 2)

    def test_getresponse_failure_not_replayed_and_next_call_uses_new_connection(self):
        factory = Factory([http.client.RemoteDisconnected("synthetic")], [response()])
        _, opener = self.opener(factory)
        with self.assertRaisesRegex(urllib.error.URLError, "transport_failed"):
            opener.open(self.request())
        self.assertEqual(len(factory.calls), 1)
        self.assertEqual(len(factory.connections[0].requests), 1)
        self.assertEqual(factory.connections[0].closes, 1)
        with opener.open(self.request()) as result:
            result.read()
        self.assertEqual(len(factory.calls), 2)

    def test_request_failure_is_never_replayed(self):
        factory = Factory([response()], [response()])
        handler, opener = self.opener(factory)
        connection = factory(mod.SITE, 443)
        handler._connection = connection
        original = connection.request
        def fail(*args, **kwargs):
            original(*args, **kwargs)
            raise OSError("synthetic write failure")
        connection.request = fail
        with self.assertRaisesRegex(urllib.error.URLError, "transport_failed"):
            opener.open(self.request())
        self.assertEqual(len(connection.requests), 1)
        self.assertEqual(len(factory.calls), 1)
        self.assertEqual(connection.closes, 1)
        with opener.open(self.request()) as result:
            result.read()
        self.assertEqual(len(factory.calls), 2)

    def test_read_failure_discards_and_next_call_is_new_connection(self):
        factory = Factory([response(body=b"x", length=20)], [response()])
        _, opener = self.opener(factory)
        with opener.open(self.request()) as result:
            with self.assertRaisesRegex(urllib.error.URLError, "response_failed"):
                result.read()
        self.assertEqual(factory.connections[0].closes, 1)
        with opener.open(self.request()) as result:
            result.read()
        self.assertEqual(len(factory.calls), 2)

    def test_server_connection_close_discards_after_complete_read(self):
        factory = Factory([response(extra="Connection: close\r\n")], [response()])
        _, opener = self.opener(factory)
        for _ in range(2):
            with opener.open(self.request()) as result:
                result.read()
        self.assertEqual(len(factory.calls), 2)
        self.assertEqual(factory.connections[0].closes, 1)

    def test_explicit_request_close_is_honored_even_if_server_omits_it(self):
        factory = Factory([response()], [response()])
        _, opener = self.opener(factory)
        req = self.request()
        req.add_header("Connection", "close")
        with opener.open(req) as result:
            result.read()
        with opener.open(self.request()) as result:
            result.read()
        self.assertEqual(len(factory.calls), 2)
        self.assertEqual(factory.connections[0].closes, 1)

    def test_chunked_response_fully_consumed_keeps_connection(self):
        raw = (b"HTTP/1.1 200 Synthetic\r\nTransfer-Encoding: chunked\r\n\r\n"
               b"2\r\n{}\r\n0\r\n\r\n")
        chunked = http.client.HTTPResponse(Socket(raw))
        chunked.begin()
        factory = Factory([chunked, response()])
        _, opener = self.opener(factory)
        with opener.open(self.request()) as result:
            self.assertEqual(result.read(100), b"{}")
        with opener.open(self.request()) as result:
            result.read()
        self.assertEqual(len(factory.calls), 1)

    def test_unread_and_partially_read_contexts_discard(self):
        for amount in (None, 1):
            factory = Factory([response()], [response()])
            _, opener = self.opener(factory)
            with opener.open(self.request()) as result:
                if amount is not None:
                    result.read(amount)
            self.assertEqual(factory.connections[0].closes, 1)
            with opener.open(self.request()) as result:
                result.read()
            self.assertEqual(len(factory.calls), 2)
            self.assertEqual(sum(len(c.requests) for c in factory.connections), 2)

    def test_abandoned_unread_response_is_closed_before_next_write(self):
        factory = Factory([response()], [response()])
        _, opener = self.opener(factory)
        old = opener.open(self.request())
        with opener.open(self.request()) as result:
            result.read()
        self.assertTrue(old.closed)
        self.assertEqual(len(factory.calls), 2)
        self.assertEqual(factory.connections[0].closes, 1)
        old.close()  # A late close cannot discard the newer connection.
        self.assertEqual(factory.connections[1].closes, 0)

    def test_idle_expiration_happens_before_new_request_without_replay(self):
        now = [0.0]
        factory = Factory([response(), response()], [response()])
        _, opener = self.opener(factory, clock=lambda: now[0])
        with opener.open(self.request()) as result:
            result.read()
        now[0] = 19.9
        with opener.open(self.request()) as result:
            result.read()
        self.assertEqual(len(factory.calls), 1)
        now[0] = 40.0
        with opener.open(self.request()) as result:
            result.read()
        self.assertEqual(len(factory.calls), 2)
        self.assertEqual(factory.connections[0].closes, 1)
        self.assertEqual(sum(len(c.requests) for c in factory.connections), 3)

    def test_partial_chunks_and_readinto_can_complete_and_reuse(self):
        factory = Factory([response(body=b"abcd"), response()])
        _, opener = self.opener(factory)
        with opener.open(self.request()) as result:
            self.assertEqual(result.read(2), b"ab")
            buffer = bytearray(2)
            self.assertEqual(result.readinto(buffer), 2)
            self.assertEqual(buffer, b"cd")
        with opener.open(self.request()) as result:
            result.read()
        self.assertEqual(len(factory.calls), 1)


if __name__ == "__main__":
    unittest.main()

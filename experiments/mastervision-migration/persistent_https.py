"""Sequential, account-bound urllib transport; requests are never replayed.

Only fully consumed HTTP/1.1 responses can leave a connection reusable.  The
caller retains its response-size bound and its uncertain-mutation handling.
"""
import http.client
import socket
import time
import urllib.error
import urllib.parse
import urllib.request


SITE = "my-lk.mastervision.su"
ERROR_URL = "https://" + SITE + "/api/v2/mcp"


class PersistentHTTPS(urllib.request.HTTPSHandler):
    """A single sequential HTTPS connection to Master Vision on port 443.

    connection_factory has the HTTPSConnection(host, port, timeout=, context=)
    signature.  Injecting it and clock allows tests without network access.
    Instances are not intended for concurrent requests.
    """

    def __init__(self, connection_factory=None, clock=None, idle_timeout=20.0):
        super().__init__()
        if not isinstance(idle_timeout, (int, float)) or not 0 < idle_timeout <= 20:
            raise ValueError("persistent_https_idle_timeout_invalid")
        self._factory = connection_factory or http.client.HTTPSConnection
        self._clock = clock or time.monotonic
        self._idle_timeout = idle_timeout
        self._connection = None
        self._active = None
        self._last_used = None

    @staticmethod
    def _validate(req):
        url = req.full_url
        try:
            parsed = urllib.parse.urlsplit(url)
            valid = (isinstance(url, str) and not any(ord(c) <= 32 or ord(c) == 127 for c in url)
                     and parsed.scheme == "https" and parsed.netloc == SITE
                     and not parsed.fragment and req.host == SITE
                     and not getattr(req, "_tunnel_host", None) and not req.has_proxy())
        except (ValueError, TypeError, AttributeError):
            valid = False
        if not valid:
            raise urllib.error.URLError("persistent_https_destination_rejected")
        if req.data is not None and not isinstance(req.data, (bytes, bytearray, memoryview)):
            raise urllib.error.URLError("persistent_https_body_invalid")
        seen = set()
        for name, value in req.header_items():
            lowered = name.lower()
            if (lowered in seen or not isinstance(value, str)
                    or "\r" in value or "\n" in value
                    or lowered == "proxy-authorization"
                    or lowered == "host" and value != SITE
                    or lowered == "transfer-encoding"):
                raise urllib.error.URLError("persistent_https_headers_rejected")
            seen.add(lowered)
            if lowered == "content-length":
                expected = len(req.data) if req.data is not None else 0
                if value != str(expected):
                    raise urllib.error.URLError("persistent_https_headers_rejected")

    def https_request(self, req):
        self._validate(req)
        return self.do_request_(req)

    def http_request(self, req):
        # build_opener also installs HTTPHandler: reject before it can connect.
        raise urllib.error.URLError("persistent_https_destination_rejected")

    def _discard(self, connection=None):
        current = self._connection
        if connection is not None and current is not connection:
            return
        self._connection = None
        self._last_used = None
        if current is not None:
            try:
                current.close()
            except Exception:
                pass

    def close(self):
        self._discard()
        if self._active is not None:
            lease, self._active = self._active, None
            lease.close()

    def https_open(self, req):
        self._validate(req)
        # An abandoned response never shares its connection with another call.
        if self._active is not None:
            self._active.close()
        if (self._connection is not None and self._last_used is not None
                and self._clock() - self._last_used >= self._idle_timeout):
            self._discard()
        timeout = getattr(req, "timeout", socket._GLOBAL_DEFAULT_TIMEOUT)
        connection = self._connection
        try:
            if connection is None:
                connection = self._factory(SITE, 443, timeout=timeout, context=self._context)
                self._connection = connection
            else:
                connection.timeout = timeout
                if connection.sock is not None:
                    connection.sock.settimeout(timeout)
            headers = dict(req.header_items())
            headers["Host"] = SITE
            connection.request(req.get_method(), req.selector or "/", body=req.data, headers=headers)
            response = connection.getresponse()
        except (OSError, http.client.HTTPException):
            self._discard(connection)
            raise urllib.error.URLError("persistent_https_transport_failed") from None
        if response.status != 200:
            self._discard(connection)
            response.close()
            # Raising here bypasses urllib's redirect handlers, including 30x.
            raise urllib.error.HTTPError(ERROR_URL, response.status,
                                         "persistent_https_http_failed", response.headers, None)
        response.code = response.status
        response.msg = response.reason
        response.url = req.full_url
        force_close = any(name.lower() == "connection" and value.lower() == "close"
                          for name, value in headers.items())
        lease = _ResponseLease(self, connection, response, force_close)
        self._active = lease
        lease.install()
        return response


class _ResponseLease:
    """Track the original HTTPResponse without replacing its urllib interface."""

    def __init__(self, owner, connection, response, force_close):
        self.owner, self.connection, self.response = owner, connection, response
        self.force_close, self.finished = force_close, False
        self.consumed = response.length == 0
        self.original_close = response.close

    def install(self):
        for name in ("read", "read1", "readinto", "readinto1"):
            original = getattr(self.response, name, None)
            if original is not None:
                setattr(self.response, name, self._reader(original))
        self.response.close = self.close

    def _reader(self, original):
        def read(*args, **kwargs):
            try:
                result = original(*args, **kwargs)
            except (OSError, http.client.HTTPException):
                self.owner._discard(self.connection)
                self.close()
                raise urllib.error.URLError("persistent_https_response_failed") from None
            self.consumed = (self.response.length == 0 or
                             self.response.length is None and self.response.isclosed())
            if self.consumed:
                self._finish()
            return result
        return read

    def _finish(self):
        if self.finished:
            return
        self.finished = True
        if self.owner._active is self:
            self.owner._active = None
        if not self.consumed or self.response.will_close or self.force_close:
            self.owner._discard(self.connection)
        elif self.owner._connection is self.connection:
            self.owner._last_used = self.owner._clock()

    def close(self):
        self._finish()
        self.original_close()

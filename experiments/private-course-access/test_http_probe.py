"""Session lifecycle regression checks; no Frappe, network or real user data."""
import json
import sys
import types
import unittest
from datetime import datetime, timezone
from unittest.mock import patch

import http_probe as probe


class JSONTransportTests(unittest.TestCase):
    def check_body(self, arguments):
        class Response:
            status = 200

            def __enter__(self):
                return self

            def __exit__(self, *args):
                pass

            def read(self, limit):
                return b'{"message": []}'

        with patch.object(probe, "build_opener") as opener:
            opener.return_value.open.return_value = Response()
            probe.request(probe.SITE, "/api/method/synthetic", arguments,
                          ("synthetic-session", "synthetic-csrf"), post=True)
            req = opener.return_value.open.call_args.args[0]
        self.assertEqual(json.loads(req.data), arguments)
        self.assertEqual(req.get_header("Content-type"), "application/json")
        self.assertEqual(req.get_header("X-frappe-csrf-token"), "synthetic-csrf")
        self.assertEqual(req.method, "POST")

    def test_typed_filters_are_native_json_objects(self):
        self.check_body({"filters": {"enrolled": 1, "custom_avo_id": "1"}, "limit_page_length": 100})

    def test_self_enrollment_doc_remains_native_json(self):
        self.check_body({"doc": {"doctype": "LMS Enrollment", "course": "synthetic-course", "member": "synthetic-user"}})


class SessionLifecycleTests(unittest.TestCase):
    def exercise(self, failure=None):
        calls = []
        local = types.SimpleNamespace(session=object(), session_obj=object(), request=object(),
                                      request_ip="old", form_dict={}, lang="ru")
        previous = vars(local).copy()
        fr = types.SimpleNamespace(
            local=local, _dict=dict, generate_hash=lambda: "synthetic-csrf",
            utils=types.SimpleNamespace(now_datetime=datetime.now, add_to_date=lambda *a, **k: datetime.now()),
            db=types.SimpleNamespace(delete=lambda dt, filters: calls.append((dt, filters)), commit=lambda: None),
            cache=types.SimpleNamespace(hdel=lambda *a: None),
        )
        sessions = types.ModuleType("frappe.sessions")
        original_callback = lambda *a, **kw: calls.append("unexpected-metadata-update")
        sessions.update_user_metadata = original_callback

        class Session:
            def __init__(self, **kwargs):
                if failure == "before_sid":
                    raise RuntimeError("synthetic initialization failure")
                self.sid = "only-synthetic-session"
                if failure == "after_sid":
                    raise RuntimeError("synthetic initialization failure")
                # Installed Frappe parses the cached value with fromisoformat and
                # compares it to UTC-aware now. A datetime or naive string fails.
                expiry = datetime.fromisoformat(kwargs["session_end"])
                seconds = (expiry - datetime.now(timezone.utc)).total_seconds()
                if not 300 < seconds <= 900:
                    raise AssertionError("bounded UTC-aware ISO expiry required")
                self.data = types.SimpleNamespace(data=types.SimpleNamespace())
                sessions.update_user_metadata()

            def update(self, force=False):
                sessions.update_user_metadata()
                if failure == "update":
                    raise RuntimeError("synthetic cache update failure")

        sessions.Session = Session
        frappe = types.ModuleType("frappe")
        frappe.sessions = sessions
        test = types.ModuleType("werkzeug.test")
        test.EnvironBuilder = lambda **kw: types.SimpleNamespace(get_environ=lambda: {})
        wrappers = types.ModuleType("werkzeug.wrappers")
        wrappers.Request = lambda env: object()
        modules = {"frappe": frappe, "frappe.sessions": sessions,
                   "werkzeug.test": test, "werkzeug.wrappers": wrappers}
        with patch.dict(sys.modules, modules):
            if failure:
                with self.assertRaises(RuntimeError):
                    with probe.temporary_session(fr, "synthetic-user", probe.SITE):
                        if failure == "request":
                            raise RuntimeError("synthetic HTTP failure")
            else:
                with probe.temporary_session(fr, "synthetic-user", probe.SITE) as credentials:
                    self.assertEqual(credentials, ("only-synthetic-session", "synthetic-csrf"))
        self.assertEqual(vars(local), previous)
        self.assertIs(sessions.update_user_metadata, original_callback)
        expected = [] if failure == "before_sid" else [
            ("Sessions", {"sid": "only-synthetic-session", "user": "synthetic-user"})]
        self.assertEqual(calls, expected)

    def test_installed_session_expiry_contract_and_cleanup(self):
        self.exercise()

    def test_initialization_failures_clean_only_allocated_session(self):
        for stage in ("before_sid", "after_sid"):
            with self.subTest(stage=stage):
                self.exercise(stage)

    def test_cache_failure_restores_context_and_metadata_callback(self):
        self.exercise("update")

    def test_http_failure_cleans_session(self):
        self.exercise("request")


if __name__ == "__main__":
    unittest.main()

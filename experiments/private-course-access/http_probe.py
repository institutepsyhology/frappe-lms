"""HTTPS access checks using two temporary, audited, in-memory-only sessions.

Run explicitly from a trusted Administrator bench context after reviewing this
operator. User/document arguments stay private; output contains booleans only.
No login endpoint, passwords, API keys, tracking endpoints or browser JS are used.
"""
import json
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from urllib.error import HTTPError
from urllib.parse import quote, urlencode
from urllib.request import HTTPRedirectHandler, Request, build_opener
from unittest.mock import patch


SITE = "my-lk.mv-centr.ru"
STAFF = {"System Manager", "Moderator", "Course Creator", "Batch Evaluator"}
MISSING = object()


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None  # Never forward a test cookie to another URL/origin.


def request(site, path, args=None, credentials=None, post=False):
    if site != SITE or not path.startswith(("/api/", "/personal/training/")) or "://" in path:
        raise ValueError("probe_destination_rejected")
    values = args or {}
    query = {k: json.dumps(v) if isinstance(v, (dict, list)) else v for k, v in values.items()}
    payload = json.dumps(values).encode() if post else None
    url = "https://" + site + path + (("?" + urlencode(query)) if query and not post else "")
    headers = {"Accept": "application/json", "Accept-Language": "en", "User-Agent": "LMS-access-verification"}
    if credentials:
        headers.update({"Cookie": "sid=" + credentials[0] + "; user_lang=en", "X-Frappe-CSRF-Token": credentials[1]})
    if post:
        headers["Content-Type"] = "application/json"
    req = Request(url, data=payload, headers=headers, method="POST" if post else "GET")
    try:
        response = build_opener(NoRedirect).open(req, timeout=25)
    except HTTPError as error:
        response = error
    with response:
        raw = response.read(8_000_001)
        if len(raw) > 8_000_000:
            raise RuntimeError("probe_response_too_large")
        try:
            data = json.loads(raw)
        except (ValueError, UnicodeError):
            data = None
        return response.status, data


@contextmanager
def temporary_session(fr, user, site):
    """Session.start without LoginManager (which can terminate other logins).

    Suppress only this process's session metadata callback during creation/update.
    The real HTTPS requests resume a fresh session and do not force metadata writes.
    """
    from frappe.sessions import Session
    from werkzeug.test import EnvironBuilder
    from werkzeug.wrappers import Request as WerkzeugRequest

    attrs = ("session", "session_obj", "request", "request_ip", "form_dict", "lang")
    previous = {key: getattr(fr.local, key, MISSING) for key in attrs}
    sid = None
    try:
        fr.local.request = WerkzeugRequest(EnvironBuilder(base_url="https://" + site).get_environ())
        fr.local.request_ip, fr.local.form_dict, fr.local.lang = "127.0.0.1", fr._dict(), "en"
        session = Session.__new__(Session)  # Retain the object if __init__ fails after allocating its SID.
        with patch("frappe.sessions.update_user_metadata", lambda *a, **kw: None):
            try:
                Session.__init__(session, user=user, user_type="Website User", full_name="",
                                 session_end=(datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat(),
                                 audit_user="Administrator")
            finally:
                candidate = getattr(session, "sid", None)
                sid = candidate if candidate and candidate != "Guest" else None
            fr.local.session_obj = session
            token = session.data.data.csrf_token = fr.generate_hash()
            session.data.data.session_expiry = "00:10:00"
            session.data.data.lang = "en"
            session.update(force=True)
        yield sid, token
    finally:
        try:
            if sid:
                # Delete exactly our own session, never other sessions or user state.
                fr.db.delete("Sessions", {"sid": sid, "user": user})
                fr.db.commit()
                fr.cache.hdel("session", sid)
        finally:
            for key, value in previous.items():
                if value is MISSING:
                    if hasattr(fr.local, key):
                        delattr(fr.local, key)
                else:
                    setattr(fr.local, key, value)


def _ordinary(fr, user, course, enrolled):
    from lms.lms.permissions import can_author_course
    row = fr.db.get_value("User", user, ["enabled", "user_type"], as_dict=True)
    return bool(row and row.enabled and row.user_type == "Website User" and
                not (STAFF & set(fr.get_roles(user))) and not can_author_course(course, user=user) and
                bool(fr.db.exists("LMS Enrollment", {"member": user, "course": course})) == enrolled)


def visible_as_expected(status, visible, allowed):
    return status in (200, 401, 403, 417) and bool(status == 200 and visible) == allowed


def no_material(data):
    return data is None or (isinstance(data, dict) and not any(data.get(k) for k in
        ("body", "content", "youtube", "instructor_content", "instructor_notes", "videos")))


def _state(fr, users, course):
    return {
        "enrollments": fr.get_all("LMS Enrollment", filters={"member": ["in", users], "course": course},
                                  fields=["name", "member", "current_lesson", "progress", "modified"], order_by="name"),
        "tracking": {dt: fr.get_all(dt, filters={"member": ["in", users], "course": course},
                                    fields=["name", "modified"], order_by="name")
                     for dt in ("LMS Lesson Visit", "LMS Course Progress", "LMS Video Watch Duration")},
        "login_metadata": [fr.db.get_value("User", user, ["last_login", "last_ip", "last_active"], as_dict=True)
                           for user in users],
        "session_counts": [fr.db.count("Sessions", {"user": user}) for user in users],
    }


def run(fr, *, site, member, course_id, lesson_id, outsider=None):
    """Return aggregate verification results, never identity/content/session data."""
    if site != SITE or fr.local.site != site or fr.session.user != "Administrator":
        raise RuntimeError("trusted_site_administrator_required")
    if fr.conf.get("deny_multiple_sessions") or fr.db.get_system_setting("deny_multiple_sessions"):
        raise RuntimeError("probe_would_clear_existing_sessions")
    course = fr.get_all("LMS Course", filters={"custom_avo_account": "mv-centr", "custom_avo_id": str(course_id)},
                        fields=["name", "published", "disable_self_learning"], limit_page_length=2)
    lesson = fr.get_all("Course Lesson", filters={"custom_avo_account": "mv-centr", "custom_avo_id": str(lesson_id)},
                        fields=["name", "course", "is_draft", "include_in_preview"], limit_page_length=2)
    if len(course) != 1 or len(lesson) != 1 or lesson[0].course != course[0].name:
        raise RuntimeError("ambiguous_source_identity")
    course, lesson = course[0], lesson[0]
    if course.published or not course.disable_self_learning or lesson.is_draft or lesson.include_in_preview:
        raise RuntimeError("private_release_settings_required")
    if not _ordinary(fr, member, course.name, True):
        raise RuntimeError("ordinary_enrolled_member_required")
    if outsider is None:
        candidates = fr.get_all("User", filters={"enabled": 1, "user_type": "Website User"},
                                pluck="name", order_by="creation desc", limit_page_length=250)
        outsider = next((u for u in candidates if u != member and _ordinary(fr, u, course.name, False)), None)
    if not outsider or not _ordinary(fr, outsider, course.name, False):
        raise RuntimeError("ordinary_unentitled_member_required")
    # The exact same controller used by the POST must reject before any insert.
    original_user = fr.session.user
    try:
        fr.set_user(outsider)
        rejected = False
        try:
            fr.get_doc({"doctype": "LMS Enrollment", "course": course.name, "member": outsider}).validate_course_enrollment_eligibility()
        except fr.ValidationError:
            rejected = True
        if not rejected:
            raise RuntimeError("self_enrollment_preflight_not_blocked")
    finally:
        fr.set_user(original_user)
    baseline = _state(fr, [member, outsider], course.name)
    results = {}
    try:
        with temporary_session(fr, member, site) as member_cookie, temporary_session(fr, outsider, site) as outsider_cookie:
            for label, cookie, allowed in (("assigned", member_cookie, True), ("unassigned", outsider_cookie, False), ("guest", None, False)):
                def api(method, args):
                    return request(site, "/api/method/" + method, args, cookie)
                checks = {}
                status, data = api("frappe.auth.get_logged_user", {})
                checks["session_identity"] = (status == 200 and isinstance(data, dict) and data.get("message") == (member if allowed else outsider)) if cookie else status in (401, 403)
                status, data = api("lms.lms.utils.get_course_details", {"course": course.name})
                value = data.get("message") if isinstance(data, dict) else None
                checks["course_visibility"] = visible_as_expected(status, isinstance(value, dict) and value.get("name") == course.name, allowed) and (allowed or value in (None, {}))
                status, data = request(site, "/api/method/lms.lms.utils.get_courses", {"filters": {"enrolled": 1, "custom_avo_id": str(course_id)}, "limit_page_length": 100}, cookie, post=True)
                rows = data.get("message", []) if isinstance(data, dict) else []
                checks["enrolled_listing"] = visible_as_expected(status, isinstance(rows, list) and any(isinstance(r, dict) and r.get("name") == course.name for r in rows), allowed)
                status, data = api("lms.lms.avo_course_routes.resolve", {"course_id": str(course_id), "lesson_id": str(lesson_id)})
                target = data.get("message") if isinstance(data, dict) else None
                visible = status == 200 and isinstance(target, dict) and target.get("lesson_name") == lesson.name
                checks["avo_route_authorization"] = visible_as_expected(status, visible, allowed) and (allowed or target in (None, {}))
                status, data = api("lms.lms.avo_course_routes.resolve_course_start", {"course_id": str(course_id)})
                start = data.get("message") if isinstance(data, dict) else None
                checks["course_entrypoint"] = visible_as_expected(status, isinstance(start, dict) and start.get("course_name") == course.name, allowed) and (allowed or start in (None, {}))
                if not target:
                    target = {"chapter_number": 1, "lesson_number": 1}
                status, data = api("lms.lms.avo_course_routes.get_lesson_by_source", {"course_id": str(course_id), "lesson_id": str(lesson_id)})
                value = data.get("message") if isinstance(data, dict) else None
                checks["source_lesson"] = visible_as_expected(status, isinstance(value, dict) and value.get("name") == lesson.name and not value.get("locked"), allowed) and (allowed or no_material(value))
                if allowed:
                    position = target
                status, data = api("lms.lms.utils.get_lesson", {"course": course.name, "chapter": position["chapter_number"], "lesson": position["lesson_number"]})
                value = data.get("message") if isinstance(data, dict) else None
                checks["lesson_content"] = visible_as_expected(status, isinstance(value, dict) and value.get("name") == lesson.name and not value.get("no_preview") and not value.get("locked"), allowed) and (allowed or no_material(value))
                checks["instructor_fields_hidden"] = not isinstance(value, dict) or not (value.get("instructor_content") or value.get("instructor_notes"))
                status, data = request(site, "/api/resource/Course%20Lesson/" + quote(lesson.name, safe=""), credentials=cookie)
                checks["raw_lesson_denied"] = status in (401, 403)
                status, _ = request(site, "/personal/training/" + str(course_id) + "/view/" + str(lesson_id), credentials=cookie)
                checks["legacy_shell_loads"] = status in (200, 301, 302, 303, 307, 308)
                results[label] = checks
            status, data = request(site, "/api/method/frappe.client.insert", {"doc": {"doctype": "LMS Enrollment", "course": course.name, "member": outsider}}, outsider_cookie, post=True)
            encoded = json.dumps(data, ensure_ascii=False).lower()
            results["self_enrollment_policy_rejected"] = status in (403, 417) and isinstance(data, dict) and data.get("exc_type") == "ValidationError" and any(s in encoded for s in ("self-learning", "самостоятель", "самообуч"))
    finally:
        results["learner_state_unchanged"] = _state(fr, [member, outsider], course.name) == baseline
    results["ok"] = all(all(v.values()) if isinstance(v, dict) else v for v in results.values())
    return results

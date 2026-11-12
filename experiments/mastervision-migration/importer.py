"""Draft-only MasterVision migration through its account-bound Frappe MCP.

Lesson text, image bytes and authentication stay in memory/private source stores.
This module returns numeric identities and fixed diagnostic codes only.
"""
import copy
import importlib.util
import json
from pathlib import Path
import re
import time
import urllib.error
import urllib.request


ACCOUNT = "mastervision"
ORIGIN = "https://shop.mastervision.su"
SITE = "my-lk.mastervision.su"
SERVER_NAME = "my_lk_mastervision_su"
METHOD = "lms.lms.avo_import.import_lesson"
DIAGNOSTIC = re.compile(r"[a-z0-9_]{1,80}")


class Stop(Exception):
    """Identity/transport failure or an uncertain mutation: stop the whole run."""


class Review(Exception):
    """A known source/structure problem; problems contain metadata only."""
    def __init__(self, code, problems=None):
        super().__init__(code)
        self.problems = [] if problems is None else problems


def authentication(workspace=None):
    roots = [Path(workspace)] if workspace is not None else Path(__file__).resolve().parents
    helper = next((root / "frappe-mcp/headers.py" for root in roots
                   if (root / "frappe-mcp/headers.py").is_file()), None)
    if helper is None:
        raise Stop("authentication_helper_missing")
    spec = importlib.util.spec_from_file_location("mastervision_mcp_headers", helper)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.authenticated_headers(SITE), module.NoRedirect


class MCPClient:
    site, account = SITE, ACCOUNT

    def __init__(self, workspace=None):
        self.auth, self.n = {}, 0
        try:
            self.auth, no_redirect = authentication(workspace)
            if not isinstance(self.auth, dict) or set(self.auth) != {"Cookie"}:
                raise Stop("authentication_invalid")
            self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), no_redirect())
            init = self.rpc("initialize", {"protocolVersion": "2025-11-25", "capabilities": {},
                                          "clientInfo": {"name": "mastervision-draft-import", "version": "1.0"}})
            if init.get("serverInfo", {}).get("name") != SERVER_NAME:
                raise Stop("wrong_frappe_site")
        except Stop:
            self.auth.clear()
            raise
        except Exception:
            self.auth.clear()
            raise Stop("mcp_authentication_failed") from None

    def rpc(self, method, params):
        self.n += 1
        data = json.dumps({"jsonrpc": "2.0", "id": self.n, "method": method, "params": params},
                          ensure_ascii=True, allow_nan=False).encode()
        req = urllib.request.Request("https://" + SITE + "/api/v2/mcp", data=data,
            headers={"Content-Type": "application/json", "Accept": "application/json, text/event-stream", **self.auth})
        arguments = params.get('arguments', {}) if isinstance(params, dict) else {}
        readonly = method == 'initialize' or (method == 'tools/call' and isinstance(params, dict) and
            (params.get('name') in ('list_documents', 'get_document') or
             params.get('name') == 'call_method' and isinstance(arguments, dict) and
             arguments.get('method') == METHOD and isinstance(arguments.get('args'), dict) and
             arguments['args'].get('dry_run') is True))
        attempts = 3 if readonly else 1
        for attempt in range(attempts):
            try:
                with self.opener.open(req, timeout=60) as response:
                    raw = response.read(32 * 1024 * 1024 + 1)
                    if len(raw) > 32 * 1024 * 1024:
                        raise Stop("mcp_invalid_response")
                    body = json.loads(raw)
                break
            except Stop:
                raise
            except urllib.error.HTTPError as error:
                transient = error.code in (429, 502, 503, 504)
                code = ('mcp_authentication_failed' if error.code in (401, 403) else
                        'mcp_rate_limited' if error.code == 429 else 'mcp_http_failed')
                if not transient or attempt + 1 == attempts: raise Stop(code) from None
            except (urllib.error.URLError, OSError, TimeoutError):
                if attempt + 1 == attempts: raise Stop('mcp_connection_failed') from None
            except Exception:
                raise Stop('mcp_invalid_response') from None
            time.sleep(attempt + 1)
        if not isinstance(body, dict) or body.get("id") != self.n or "error" in body or not isinstance(body.get("result"), dict):
            raise Stop("mcp_invalid_response")
        return body["result"]

    def call(self, name, args):
        if name not in {"list_documents", "get_document", "call_method"} or (name == "call_method" and args.get("method") != METHOD):
            raise Stop("unsupported_mcp_method")
        result = self.rpc("tools/call", {"name": name, "arguments": args})
        if result.get("isError"):
            raise Review("mcp_rejected_request")  # Never expose remote exception bodies.
        value = result.get("structuredContent")
        if not isinstance(value, dict):
            raise Stop("mcp_invalid_response")
        return value

    def close(self):
        try:
            if self.auth:
                req = urllib.request.Request("https://" + SITE + "/api/method/logout", data=b"{}",
                                             headers={"Content-Type": "application/json", **self.auth})
                with self.opener.open(req, timeout=15):
                    pass
        except Exception:
            pass
        finally:
            self.auth.clear()


def source_id(value):
    if type(value) is int:
        value = str(value)
    if not isinstance(value, str) or not re.fullmatch(r"[1-9][0-9]{0,9}", value) or int(value) > (1 << 31) - 1:
        raise Review("invalid_source_identity")
    return value


def diagnostics(value):
    if not isinstance(value, list) or any(not isinstance(v, str) or not DIAGNOSTIC.fullmatch(v) for v in value):
        raise Stop("preview_diagnostic_invalid")
    return value


def has_images(payload):
    pending = [payload]
    while pending:
        value = pending.pop()
        if isinstance(value, dict):
            if value.get("name") == "image" or value.get("type") == "image":
                return True
            pending.extend(value.values())
        elif isinstance(value, list):
            pending.extend(value)
    return False


class Importer:
    def __init__(self, client):
        self.client = client
        self.check_site()

    def check_site(self):
        if getattr(self.client, "site", None) != SITE or getattr(self.client, "account", None) != ACCOUNT:
            raise Stop("wrong_frappe_site")

    def outline(self, course_id):
        self.check_site()
        data = self.client.call("list_documents", {"doctype": "LMS Course",
            "fields": ["name", "published", "custom_avo_account", "custom_avo_id", "custom_lms_id"],
            "filters": [["custom_avo_account", "=", ACCOUNT], ["custom_avo_id", "=", course_id]], "limit": 3})
        rows = data.get("documents")
        if not isinstance(rows, list) or data.get("has_next_page") is not False or len(rows) > 1:
            raise Review("ambiguous_course")
        if not rows:
            return {"ids": [], "course": None, "by_id": {}}
        row = rows[0]
        if not isinstance(row, dict) or row.get("custom_avo_account") != ACCOUNT or row.get("custom_avo_id") != course_id or row.get("custom_lms_id") != course_id:
            raise Review("target_course_identity_invalid")
        name = row.get("name")
        if not isinstance(name, str) or not name or row.get("published") != 0:
            raise Review("course_not_draft")
        doc = self.client.call("get_document", {"doctype": "LMS Course", "name": name})
        if any(doc.get(key) != row.get(key) for key in ("name", "published", "custom_avo_account", "custom_avo_id", "custom_lms_id")):
            raise Review("target_course_identity_invalid")
        chapters = doc.get("chapters")
        if not isinstance(chapters, list) or len(chapters) != 1 or not isinstance(chapters[0], dict) or not chapters[0].get("chapter"):
            raise Review("course_chapters_ambiguous")
        chapter = self.client.call("get_document", {"doctype": "Course Chapter", "name": chapters[0]["chapter"]})
        if chapter.get("name") != chapters[0]["chapter"] or chapter.get("course") != name or chapter.get("is_scorm_package"):
            raise Review("course_chapter_invalid")
        references = chapter.get("lessons")
        if not isinstance(references, list) or any(not isinstance(r, dict) or type(r.get("idx")) is not int or r["idx"] != i or not isinstance(r.get("lesson"), str) or not r["lesson"] for i, r in enumerate(references, 1)):
            raise Review("course_outline_invalid")
        names = [r["lesson"] for r in references]
        if len(names) != len(set(names)):
            raise Review("course_outline_invalid")
        by_name = {}
        for offset in range(0, len(names), 100):
            group = names[offset:offset + 100]
            data = self.client.call("list_documents", {"doctype": "Course Lesson", "fields": ["name", "custom_avo_account", "custom_avo_id", "custom_lms_id", "course", "chapter", "is_draft", "include_in_preview"], "filters": [["name", "in", group]], "limit": len(group)})
            rows = data.get("documents")
            if not isinstance(rows, list) or data.get("has_next_page") is not False or len(rows) != len(group):
                raise Review("course_outline_invalid")
            for row in rows:
                if not isinstance(row, dict) or row.get("name") not in group or row["name"] in by_name:
                    raise Review("course_outline_invalid")
                by_name[row["name"]] = row
        ids, by_id = [], {}
        for lesson_name in names:
            row = by_name[lesson_name]
            ident = source_id(row.get("custom_avo_id"))
            if row.get("custom_avo_account") != ACCOUNT or row.get("custom_lms_id") != ident or row.get("course") != name or row.get("chapter") != chapter["name"] or row.get("is_draft") != 1 or row.get("include_in_preview") != 0 or ident in by_id:
                raise Review("existing_lesson_not_safe")
            ids.append(ident)
            by_id[ident] = row
        return {"ids": ids, "course": name, "by_id": by_id}

    def preview(self, payload, images):
        value = self.client.call("call_method", {"method": METHOD, "args": {"payload": payload, "images": images, "dry_run": True}}).get("result")
        if not isinstance(value, dict) or value.get("account") != ACCOUNT or value.get("course_id") != source_id(payload["course_id"]) or value.get("lesson_id") != source_id(payload["lesson_id"]) or value.get("dry_run") is not True:
            raise Stop("preview_identity_invalid")
        issues, warnings = diagnostics(value.get("issues")), diagnostics(value.get("warnings"))
        if value.get("ready") is False:
            raise Review("lesson_needs_review", [{"lesson_id": source_id(payload["lesson_id"]), "codes": issues or ["lesson_needs_review"]}])
        if value.get("ready") is not True or issues or value.get("action") not in {"already_imported", "create_lesson", "create_course_and_lesson"}:
            raise Stop("preview_result_invalid")
        return value, warnings

    def import_course(self, payloads, apply=False, images_for_lesson=None, progress_callback=None):
        """Check all snapshots, then append missing drafts in exact source order.

        images_for_lesson(payload_copy) optionally returns block-key/base64 images.
        progress_callback receives IDs/status only around each verified mutation.
        A Review.problems list identifies all known preflight failures without text.
        Any failed/uncertain write is a Stop and must halt the caller's entire run.
        """
        self.check_site()
        if progress_callback is not None and not callable(progress_callback):
            raise Stop("journal_unavailable")
        if type(apply) is not bool or not isinstance(payloads, list) or not payloads:
            raise Review("invalid_payloads")
        try:
            payloads = json.loads(json.dumps(payloads, ensure_ascii=True, allow_nan=False))
        except (ValueError, TypeError, RecursionError):
            raise Review("invalid_payloads") from None
        course, title, ids = None, None, []
        for payload in payloads:
            if not isinstance(payload, dict):
                raise Review("invalid_payloads")
            if (payload.get("account"), payload.get("source_origin")) != (ACCOUNT, ORIGIN):
                raise Stop("source_account_mismatch")
            cid, lid = source_id(payload.get("course_id")), source_id(payload.get("lesson_id"))
            if any(not isinstance(payload.get(k), str) or not payload[k].strip() or len(payload[k]) > 512 for k in ("course_title", "lesson_title")) or payload.get("format") not in {"ape", "preview"}:
                raise Review("invalid_payloads")
            if (course is not None and (cid != course or payload["course_title"] != title)) or lid in ids:
                raise Review("source_manifest_conflict")
            course, title = cid, payload["course_title"]
            ids.append(lid)
        initial = self.outline(course)
        existing = initial["ids"]
        if existing != ids[:len(existing)] or len(existing) > len(ids):
            raise Review("course_order_conflict")
        problems, image_sets, warnings = [], {}, []
        for payload, ident in zip(payloads, ids):
            try:
                try:
                    images = {} if images_for_lesson is None else images_for_lesson(copy.deepcopy(payload))
                    if not isinstance(images, dict) or any(not isinstance(k, str) or not isinstance(v, str) for k, v in images.items()):
                        raise ValueError()
                    images = copy.deepcopy(images)
                except Review:
                    raise
                except Exception:
                    raise Review("image_requires_preparation") from None
                image_sets[ident] = images
                value, codes = self.preview(payload, images)
                if (value["action"] == "already_imported") != (ident in existing):
                    raise Review("course_order_conflict")
                if codes:
                    warnings.append({"lesson_id": ident, "codes": codes})
            except Review as error:
                code = str(error) if DIAGNOSTIC.fullmatch(str(error)) else "lesson_needs_review"
                if code == "mcp_rejected_request" and not image_sets.get(ident) and has_images(payload):
                    code = "image_requires_preparation"
                problems.extend(error.problems or [{"lesson_id": ident, "codes": [code]}])
        if problems:
            raise Review("course_needs_review", problems)
        created = []
        if apply:
            for payload, ident in zip(payloads[len(existing):], ids[len(existing):]):
                try:
                    current = self.outline(course)
                except Review:
                    raise Stop("course_changed_during_import") from None
                if current["ids"] != ids[:len(existing) + len(created)]:
                    raise Stop("course_changed_during_import")
                if progress_callback is not None:
                    try:
                        progress_callback({"course_id": course, "lesson_id": ident, "status": "write_started"})
                    except BaseException:
                        raise Stop("journal_unavailable") from None
                try:
                    result = self.client.call("call_method", {"method": METHOD, "args": {"payload": payload, "images": image_sets[ident], "dry_run": False}}).get("result")
                    if not isinstance(result, dict) or result.get("action") != "created" or result.get("account") != ACCOUNT or result.get("course_id") != course or result.get("lesson_id") != ident or result.get("dry_run") is not False:
                        raise Stop("write_result_uncertain")
                    verified, _ = self.preview(payload, image_sets[ident])
                    if verified["action"] != "already_imported" or self.outline(course)["ids"] != ids[:len(existing) + len(created) + 1]:
                        raise Stop("write_result_uncertain")
                    if progress_callback is not None:
                        progress_callback({"course_id": course, "lesson_id": ident, "status": "created"})
                except BaseException as exc:
                    stopped = Stop('write_result_uncertain')
                    if isinstance(exc, (Stop, Review)) and DIAGNOSTIC.fullmatch(str(exc)):
                        stopped.reason = str(exc)
                    raise stopped from None
                created.append(ident)
            try:
                final = self.outline(course)
            except Review:
                raise Stop("final_order_mismatch") from None
            if final["ids"] != ids:
                raise Stop("final_order_mismatch")
        return {"account": ACCOUNT, "course_id": course,
                "status": "already_present" if existing == ids else "created" if apply else "ready",
                "lesson_ids": ids, "existing_lesson_ids": existing, "created_lesson_ids": created, "warnings": warnings}

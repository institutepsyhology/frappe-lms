"""Import uniquely identified MV-Centr contacts into Frappe; no secrets in output.

Run with --limit N --apply after reviewing dry-run totals. Existing users are
never changed. Reruns skip existing emails; ambiguous source emails are skipped.
"""
import argparse
import collections
import importlib.util
import html
import json
import re
import sqlite3
import time
from datetime import datetime, timezone
import urllib.error
import urllib.request
from contextlib import contextmanager
from pathlib import Path

def workspace_root():
    for parent in Path(__file__).resolve().parents:
        if (parent / "frappe-mcp/headers.py").is_file() and (parent / "exports/contacts-api-all-fields").is_dir():
            return parent
    raise RuntimeError("workspace_not_found")


ROOT = workspace_root()
SITE = "https://my-lk.mv-centr.ru"
EMAIL = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+\Z")
JOURNAL = ROOT / "exports/contacts-api-all-fields/mvcentr-user-import-events.jsonl"
EXCLUDED_CONTACTS = {10}


@contextmanager
def single_import():
    """Prevent concurrent imports from writing the same source contacts."""
    import msvcrt
    path = JOURNAL.with_name('mvcentr-user-import.lock')
    with path.open('a+b') as lock:
        lock.seek(0, 2)
        if lock.tell() == 0:
            lock.write(b'0')
            lock.flush()
        lock.seek(0)
        try:
            msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError as exc:
            raise RuntimeError('another_import_is_running') from exc
        try:
            yield
        finally:
            lock.seek(0)
            msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


DIRECT_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())


def log_event(ident, status):
    if type(ident) is not int or ident < 1 or not re.fullmatch(r"[a-z_]{1,50}", status):
        raise ValueError("invalid_journal_entry")
    with JOURNAL.open("a", encoding="utf-8") as out:
        out.write(json.dumps({"at": datetime.now(timezone.utc).isoformat(), "contact_id": ident,
                              "account": "mv-centr", "status": status}, ensure_ascii=True) + "\n")


def read_user(request):
    for attempt in range(3):
        try:
            with DIRECT_OPENER.open(request, timeout=20) as response:
                rows = json.load(response).get("data")
                if not isinstance(rows, list) or len(rows) != 1:
                    raise ValueError('user_readback_not_unique')
                return rows[0]
        except urllib.error.HTTPError as exc:
            if exc.code not in (429, 500, 502, 503, 504) or attempt == 2:
                raise
        except (urllib.error.URLError, TimeoutError, OSError):
            if attempt == 2:
                raise
        time.sleep(2 ** attempt)


def create_user(request):
    """Only retry a definitive server-side throttle rejection, never a timeout."""
    for attempt in range(3):
        try:
            with DIRECT_OPENER.open(request, timeout=30) as response:
                return response.status
        except urllib.error.HTTPError as exc:
            try:
                exc.avo_error = json.load(exc)
            except Exception:
                exc.avo_error = {}
            trace = str(exc.avo_error.get('exc') or '')
            throttled = (exc.code == 417 and exc.avo_error.get('exc_type') == 'ValidationError'
                         and 'in throttle_user_creation' in trace)
            if not throttled or attempt == 2:
                raise
            time.sleep(60)


def load():
    db = sqlite3.connect((ROOT / "exports/contacts-api-all-fields/contacts.sqlite").resolve().as_uri() + "?mode=ro", uri=True)
    for ident, raw in db.execute("SELECT id, record_json FROM contacts ORDER BY id"):
        yield ident, json.loads(raw)


def email_of(record):
    return str((record.get("contact") or {}).get("email") or "").strip().lower()


def marketing_optout(record):
    contact = record.get('contact') or {}
    values = [contact.get('not_to_write'), contact.get('spam_clicked')]
    if any(value not in ('0', '1') for value in values):
        raise ValueError('invalid_source_marketing_flags')
    return int('1' in values)


def payload(ident, record):
    c = record.get("contact") or {}
    pwd = (record.get("credentials") or {}).get("password")
    email = email_of(record)
    if not EMAIL.fullmatch(email) or not isinstance(pwd, str) or not pwd:
        return None
    return {"email": email, "first_name": str(c.get("name") or email),
            "middle_name": str(c.get("middle_name") or ""), "last_name": str(c.get("last_name") or ""),
            "mobile_no": str(c.get("phone_number") or ""), "user_type": "Website User",
            "send_welcome_email": 0, "new_password": pwd, "custom_avo_contact_id": str(ident),
            "custom_avo_account": "mv-centr", "custom_avo_telegram_id": str(c.get("telegram_user_id") or ""),
            "custom_avo_telegram_username": str(c.get("telegram_user") or ""),
            "custom_avo_vk_id": str(c.get("vk_user_id") or ""),
            "custom_avo_vk_username": str(c.get("vk_user") or ""),
            "custom_no_marketing_email": marketing_optout(record)}


def saved_matches(saved, data):
    fields = ("email", "first_name", "middle_name", "last_name", "mobile_no", "custom_avo_contact_id",
              "custom_avo_account", "custom_avo_telegram_id", "custom_avo_telegram_username",
              "custom_avo_vk_id", "custom_avo_vk_username", "custom_no_marketing_email")
    def matches(key):
        actual, expected = str(saved.get(key) or ""), str(data.get(key) or "")
        if actual == expected:
            return True
        # Frappe may HTML-escape names on write. Decode only the saved value,
        # and only profile names: identity, email and contacts remain exact.
        return key in ("first_name", "middle_name", "last_name") and html.unescape(actual) == expected
    return all(matches(key) for key in fields)


def user_readback_url(email):
    from urllib.parse import urlencode
    fields = ["email", "first_name", "middle_name", "last_name", "mobile_no", "custom_avo_contact_id",
              "custom_avo_account", "custom_avo_telegram_id", "custom_avo_telegram_username",
              "custom_avo_vk_id", "custom_avo_vk_username", "custom_no_marketing_email"]
    return SITE + '/api/v2/document/User?' + urlencode({
        'filters':json.dumps([['name','=',email]]), 'fields':json.dumps(fields), 'limit':2})


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--limit", type=int, default=1)
    parser.add_argument("--retry-conflicts", action="store_true", help="повторить ранее отмеченные конфликты")
    parser.add_argument("--ids-file", type=Path, help="приватный JSON-массив ID для выборочного переноса")
    parser.add_argument("--interval", type=float, default=1.0, help="пауза между созданиями в секундах")
    args = parser.parse_args()
    if args.limit < 1:
        parser.error("limit must be positive")
    if not 0.1 <= args.interval <= 60:
        parser.error("interval must be between 0.1 and 60 seconds")
    if args.apply and JOURNAL.with_name('mvcentr-recipient-batch-pending.json').exists():
        print(json.dumps({'stopped': True, 'unresolved_batch': 1}))
        return
    selected = None
    if args.ids_file:
        values = json.loads(args.ids_file.read_text(encoding="utf-8-sig"))
        if not isinstance(values, list) or any(type(v) is not int or v < 1 for v in values):
            raise ValueError('invalid_selection')
        selected = set(values)
    frequencies = collections.Counter(email_of(record) for _, record in load())
    counts = collections.Counter()
    consecutive_issues = 0
    known_conflicts = set()
    known_created = set()
    unresolved_writes = set()
    if args.apply and JOURNAL.exists():
        with JOURNAL.open(encoding="utf-8") as entries:
            for line in entries:
                event = json.loads(line)
                if event.get("account") != "mv-centr" or type(event.get("contact_id")) is not int:
                    raise ValueError("invalid_journal_entry")
                if event.get("status") in ("unique_conflict", "validation_conflict"): known_conflicts.add(event["contact_id"])
                elif event.get("status") in ("created_verified", "present_verified"):
                    known_conflicts.discard(event["contact_id"])
                    known_created.add(event["contact_id"])
                if event.get("status") in ("write_outcome_unknown", "readback_mismatch"):
                    unresolved_writes.add(event["contact_id"])
                elif event.get("status") in ("created_verified", "resolved_not_created"):
                    unresolved_writes.discard(event["contact_id"])
        if unresolved_writes:
            print(json.dumps({"unresolved_write_outcomes": len(unresolved_writes), "stopped": True}))
            return
        if args.retry_conflicts: known_conflicts.clear()
    headers = {}
    if args.apply:
        spec = importlib.util.spec_from_file_location("frappe_headers", ROOT / "frappe-mcp/headers.py")
        helper = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(helper)
        headers = helper.authenticated_headers("my-lk.mv-centr.ru")
    for ident, record in load():
        if selected is not None and ident not in selected:
            continue
        if args.apply and ident in EXCLUDED_CONTACTS:
            counts["excluded_by_owner"] += 1
            continue
        if args.apply and ident in known_created:
            counts["existing_skipped"] += 1
            consecutive_issues = 0
            continue
        if args.apply and ident in known_conflicts:
            counts["known_conflict_skipped"] += 1
            consecutive_issues += 1
            if consecutive_issues >= 10:
                counts["stopped_consecutive_issues"] += 1
                break
            continue
        data = payload(ident, record)
        if not data:
            counts["missing_email_or_password"] += 1
            if args.apply:
                log_event(ident, "missing_email_or_password")
                consecutive_issues += 1
                if consecutive_issues >= 10:
                    counts["stopped_consecutive_issues"] += 1
                    break
            continue
        if frequencies[data["email"]] != 1:
            counts["duplicate_email"] += 1
            if args.apply:
                log_event(ident, "duplicate_source_email")
                consecutive_issues += 1
                if consecutive_issues >= 10:
                    counts["stopped_consecutive_issues"] += 1
                    break
            continue
        if not args.apply:
            counts["eligible"] += 1
            continue
        # REST resources are checked before creation; do not touch any existing account.
        url = user_readback_url(data["email"])
        data.pop("user_type", None)
        data.pop("send_welcome_email", None)
        request = urllib.request.Request(SITE + "/api/method/lms.lms.avo_user_import.import_user", data=json.dumps({"data": data}).encode(),
                                         headers={**headers, "Content-Type": "application/json"}, method="POST")
        try:
            if create_user(request) not in (200, 201):
                counts["create_error"] += 1
                break
            saved = read_user(urllib.request.Request(url, headers=headers))
            if not saved_matches(saved, data):
                counts["readback_mismatch"] += 1
                log_event(ident, "readback_mismatch")
                break
            counts["created"] += 1
            consecutive_issues = 0
            log_event(ident, "created_verified")
            if counts["created"] % 25 == 0:
                print(json.dumps({"progress_created": counts["created"]}), flush=True)
            time.sleep(args.interval)
        except urllib.error.HTTPError as exc:
            # Only publish the HTTP status and the server's exception class.
            try:
                error = getattr(exc, 'avo_error', None) or {}
                exception_type = str(error.get("exc_type") or "unknown")
                if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_.]{0,100}", exception_type):
                    exception_type = "unknown"
                diagnostic = json.dumps(error, ensure_ascii=False).lower()
                for label, terms in {"password": ("password", "парол"), "email": ("email", "e-mail", "электронн"), "phone": ("phone", "телефон"), "duplicate": ("duplicate", "already exists", "существует"), "validation": ("validation", "invalid", "недопуст"), "password_weak": ("too weak", "password strength", "password is weak", "password_strength", "weak password"), "password_short": ("at least", "minimum password", "minimum_password", "characters long", "length of the password"), "csrf": ("csrf",), "mandatory": ("mandatory", "required field", "обязательн")}.items():
                    if any(term in diagnostic for term in terms):
                        counts["diagnostic_" + label] += 1
            except Exception:
                exception_type = "unreadable"
            counts["http_" + str(exc.code) + "_" + exception_type] += 1
            counts["create_error"] += 1
            if 300 <= exc.code < 400 or exc.code >= 500:
                log_event(ident, "write_outcome_unknown")
                break
            if exc.code == 409 or exception_type in ("UniqueValidationError", "DuplicateEntryError"):
                if globals().get('AUTO_RECONCILE_RECIPIENTS'):
                    try:
                        from recipient_recovery import inspect
                        outcome=inspect(ident)
                    except Exception:
                        counts['transport_error']+=1
                        log_event(ident,'write_outcome_unknown')
                        break
                    if outcome=='present':
                        counts['create_error']-=1
                        counts['reconciled_existing']+=1
                        log_event(ident,'created_verified')
                        consecutive_issues=0
                        continue
                counts["unique_conflict_skipped"] += 1
                log_event(ident, "unique_conflict")
                consecutive_issues += 1
                if consecutive_issues >= 10:
                    counts["stopped_consecutive_issues"] += 1
                    break
                continue
            if (exc.code == 417 and exception_type == "ValidationError"
                    and 'in throttle_user_creation' not in str(error.get('exc') or '')):
                counts["validation_conflict_skipped"] += 1
                log_event(ident, "validation_conflict")
                consecutive_issues += 1
                if consecutive_issues >= 10:
                    counts["stopped_consecutive_issues"] += 1
                    break
                continue
            log_event(ident, "create_error")
            break
        except Exception as exc:
            # The response may contain credentials or personal data: never print it.
            counts["create_error"] += 1
            if isinstance(exc, urllib.error.URLError):
                counts["transport_error"] += 1
            elif isinstance(exc, TimeoutError):
                counts["timeout"] += 1
            else:
                counts["unexpected_error"] += 1
            log_event(ident, "write_outcome_unknown")
            break
        if counts["created"] >= args.limit:
            break
    print(json.dumps(dict(counts), sort_keys=True))


if __name__ == "__main__":
    with single_import():
        main()

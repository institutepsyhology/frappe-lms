"""Import uniquely identified MV-Centr contacts into Frappe; no secrets in output.

Run with --limit N --apply after reviewing dry-run totals. Existing users are
never changed. Reruns skip existing emails; ambiguous source emails are skipped.
"""
import argparse
import collections
import importlib.util
import json
import re
import sqlite3
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SITE = "https://my-lk.mv-centr.ru"
EMAIL = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+\Z")


def load():
    db = sqlite3.connect((ROOT / "exports/contacts-api-all-fields/contacts.sqlite").resolve().as_uri() + "?mode=ro", uri=True)
    for ident, raw in db.execute("SELECT id, record_json FROM contacts ORDER BY id"):
        yield ident, json.loads(raw)


def email_of(record):
    return str((record.get("contact") or {}).get("email") or "").strip().lower()


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
            "custom_avo_vk_username": str(c.get("vk_user") or "")}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--limit", type=int, default=1)
    args = parser.parse_args()
    if args.limit < 1:
        parser.error("limit must be positive")
    frequencies = collections.Counter(email_of(record) for _, record in load())
    counts = collections.Counter()
    headers = {}
    if args.apply:
        spec = importlib.util.spec_from_file_location("frappe_headers", ROOT / "frappe-mcp/headers.py")
        helper = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(helper)
        headers = helper.authenticated_headers("my-lk.mv-centr.ru")
    for ident, record in load():
        data = payload(ident, record)
        if not data:
            counts["missing_email_or_password"] += 1
            continue
        if frequencies[data["email"]] != 1:
            counts["duplicate_email"] += 1
            continue
        if not args.apply:
            counts["eligible"] += 1
            continue
        # REST resources are checked before creation; do not touch any existing account.
        from urllib.parse import quote
        url = SITE + "/api/v2/document/User/" + quote(data["email"], safe="")
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=20):
                counts["existing_skipped"] += 1
                continue
        except urllib.error.HTTPError as exc:
            if exc.code != 404:
                counts["read_error"] += 1
                break
        request = urllib.request.Request(SITE + "/api/v2/document/User", data=json.dumps(data).encode(),
                                         headers={**headers, "Content-Type": "application/json"}, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                if response.status not in (200, 201):
                    counts["create_error"] += 1
                    break
            counts["created"] += 1
        except urllib.error.HTTPError as exc:
            # Only publish the HTTP status and the server's exception class.
            try:
                error = json.load(exc)
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
            break
        except Exception:
            # The response may contain credentials or personal data: never print it.
            counts["create_error"] += 1
            break
        if counts["created"] >= args.limit:
            break
    print(json.dumps(dict(counts), sort_keys=True))


if __name__ == "__main__":
    main()


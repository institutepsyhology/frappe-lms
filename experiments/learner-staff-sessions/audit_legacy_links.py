"""Offline MV-Centr login-link audit; never redeem or print source values."""
from __future__ import annotations

import argparse
from collections import Counter
from contextlib import closing
import hashlib
import json
from pathlib import Path
import sqlite3
from urllib.parse import parse_qsl, urlsplit
from server_archive_sink import PROFILE


API_ORIGIN = PROFILE.api_origin
SHOP_HOST = PROFILE.shop_host
LOGIN_PATH = '/personal/auth/secure-login'


def inspect_record(source_id, record):
    """Return fixed status labels and private comparison material only.

    Callers must never serialize the second return value. URL material is not
    normalized or changed: this audit compares the original archived strings.
    """
    if type(source_id) is not int or source_id < 1 or not isinstance(record, dict):
        return 'invalid_record', None
    if record.get('source') != API_ORIGIN:
        return 'wrong_source_account', None
    contact = record.get('contact')
    if not isinstance(contact, dict) or str(contact.get('id')) != str(source_id):
        return 'source_id_mismatch', None
    links = record.get('auth_links')
    if not isinstance(links, dict):
        return 'missing_link', None
    url = links.get('user')
    if url in ('', None):
        return 'missing_link', None
    if not isinstance(url, str) or len(url) > 8192:
        return 'invalid_link_type_or_length', None
    fields = links.get('api_fields')
    api = record.get('api_data')
    raw = api.get('list') if isinstance(api, dict) else None
    if (not isinstance(fields, dict) or not isinstance(raw, dict)
            or fields.get('link_personal_auth') != url
            or raw.get('link_personal_auth') != url):
        return 'source_copy_mismatch', None
    if any(ord(char) < 33 or ord(char) == 127 for char in url):
        return 'invalid_url', None
    try:
        parts = urlsplit(url)
        if (parts.scheme != 'https' or parts.netloc != SHOP_HOST
                or parts.path != LOGIN_PATH or parts.fragment):
            return 'unexpected_url_shape', None
        pairs = parse_qsl(parts.query, keep_blank_values=True,
                          strict_parsing=True, max_num_fields=8,
                          encoding='utf-8', errors='strict')
    except (ValueError, UnicodeError):
        return 'invalid_url', None
    if len(pairs) != 2 or sorted(key for key, _ in pairs) != ['uid', 'vc']:
        return 'unexpected_query_fields', None
    query = dict(pairs)
    token = query['vc']
    if not token or any(ord(char) < 33 or ord(char) == 127 for char in token):
        return 'empty_or_invalid_token', None
    # An in-memory collision check, not a persistent credential verifier.
    status = 'verified' if query['uid'] == str(source_id) else 'url_uid_mismatch'
    return status, hashlib.sha256(token.encode('utf-8')).digest()


def audit(database):
    """One read-only streaming pass. No usernames, tokens or URLs in output."""
    statuses = Counter()
    seen_tokens = {}
    collisions = 0
    database = Path(database).resolve()
    with closing(sqlite3.connect(database.as_uri() + '?mode=ro', uri=True)) as db:
        db.execute('PRAGMA query_only=ON')
        db.execute('PRAGMA cache_size=-2048')
        db.execute('PRAGMA mmap_size=0')
        for source_id, raw in db.execute('SELECT id, record_json FROM contacts ORDER BY id'):
            try:
                record = json.loads(raw)
            except (ValueError, TypeError, UnicodeError):
                statuses['invalid_json'] += 1
                continue
            status, token_hash = inspect_record(source_id, record)
            statuses[status] += 1
            if token_hash is not None:
                previous = seen_tokens.setdefault(token_hash, source_id)
                collisions += int(previous != source_id)
    total = sum(statuses.values())
    clean = (total > 0 and statuses['verified'] == total and collisions == 0)
    return {'account': PROFILE.account, 'mode': 'offline_read_only',
            'records_checked': total, 'status_counts': dict(sorted(statuses.items())),
            'token_reused_across_contacts': collisions, 'all_checks_passed': clean,
            'expected_format': {'scheme': 'https', 'host': SHOP_HOST,
                                'path': LOGIN_PATH, 'query_keys': ['uid', 'vc']},
            'live_validity_checked': False, 'network_requests': 0,
            'source_values_printed': False}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database', type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        report = audit(args.database)
    except (OSError, sqlite3.Error, ValueError, TypeError, UnicodeError):
        # Exception text can contain paths/source values. Emit a fixed code.
        print(json.dumps({'error': 'archive_audit_failed', 'source_values_printed': False}))
        return 2
    print(json.dumps(report, ensure_ascii=True, indent=2))
    return 0 if report['all_checks_passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())

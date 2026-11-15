"""MVC-only encrypted archive receiver, invoked over the existing SSH channel.

No HTTP route, login redemption, account mutation or public file is created.
stdin accepts one bounded request; stdout contains only receipts or fixed codes.
"""
from __future__ import annotations

import base64
from contextlib import closing
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import stat
import sys
from urllib.parse import parse_qsl, urlsplit
import zlib


FORMAT = 'mvc-frappe-archive-v1'
SITE = 'my-lk.mv-centr.ru'
API_ORIGIN = 'https://mvcentr.autoweboffice.ru'
ACCOUNT = 'mv-centr'
PAGE_FORMAT = 'mvcentr-legacy-api-snapshot-v1'
MAX_REQUEST = 32 * 1024 * 1024
MAX_PAYLOAD = 20 * 1024 * 1024
MAX_PAGE_RAW = 16 * 1024 * 1024
MAX_BATCH = 100
RESOURCES = frozenset(('contacts', 'employee', 'training', 'trainingAccess', 'accounts',
    'accountline', 'goods', 'ContactRecurringPayments', 'newsletter', 'contactnewsletterlinks',
    'contacttaglnk', 'telegrambotcontactlnk', 'funnelcontact', 'organization', 'costs',
    'costsarticle', 'goodscategory', 'goodscolor', 'goodssize', 'callcenterrequest',
    'mainsettings', 'partner', 'goodspincodes', 'advertisingchannelcompany',
    'advertisingchannel', 'advertisingchannelstatistics'))
SAFE_CODES = frozenset(('invalid_request', 'request_too_large', 'invalid_metadata',
    'invalid_records', 'invalid_payload', 'payload_too_large', 'payload_hash_mismatch',
    'invalid_link', 'invalid_page', 'invalid_page_body', 'page_too_large',
    'private_storage_required', 'invalid_archive', 'source_metadata_conflict',
    'version_conflict', 'archive_busy', 'archive_failed', 'readback_failed',
    'existing_site_key_required', 'wrong_site'))


class SinkError(Exception):
    """Only fixed code arguments; never include source values or tracebacks."""


def canonical_json(value):
    return json.dumps(value, ensure_ascii=True, sort_keys=True,
                      separators=(',', ':'), allow_nan=False).encode('utf-8')


def _no_duplicates(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise SinkError('invalid_payload')
        result[key] = value
    return result


def _invalid_constant(value):
    raise SinkError('invalid_payload')


def _json(raw):
    try:
        return json.loads(raw.decode('utf-8'), object_pairs_hook=_no_duplicates,
                          parse_constant=_invalid_constant)
    except (ValueError, TypeError, UnicodeError, RecursionError):
        raise SinkError('invalid_payload') from None


def _positive(value):
    return type(value) is int and 0 < value < 2**63


def _sha(value):
    return isinstance(value, str) and re.fullmatch(r'[a-f0-9]{64}', value) is not None


def _timestamp(value):
    if not isinstance(value, str) or not 1 <= len(value) <= 80:
        return False
    try:
        date = datetime.fromisoformat(value)
        return date.tzinfo is not None and date.utcoffset() is not None
    except ValueError:
        return False


def _base64(value, maximum, code='invalid_payload'):
    if not isinstance(value, str):
        raise SinkError(code)
    if len(value) > (maximum + 2) // 3 * 4:
        raise SinkError('payload_too_large')
    try:
        raw = base64.b64decode(value, validate=True)
    except (ValueError, UnicodeError):
        raise SinkError(code) from None
    if len(raw) > maximum:
        raise SinkError('payload_too_large')
    return raw


def _metadata(value, kind, snapshot):
    if not isinstance(value, dict):
        raise SinkError('invalid_metadata')
    if kind == 'links':
        valid = (set(value) == {'schema', 'account', 'origin', 'source_ids_sha256', 'source_count'}
            and value.get('schema') == 'mvcentr-individual-links-v1'
            and value.get('account') == ACCOUNT and value.get('origin') == API_ORIGIN
            and _sha(value.get('source_ids_sha256'))
            and isinstance(value.get('source_count'), str)
            and re.fullmatch(r'[1-9][0-9]{0,18}', value['source_count'])
            and int(value['source_count']) < 2**63)
    else:
        valid = (set(value) == {'format', 'account', 'source', 'page_size', 'snapshot'}
            and value.get('format') == PAGE_FORMAT and value.get('account') == ACCOUNT
            and value.get('source') == API_ORIGIN and value.get('snapshot') == snapshot
            and isinstance(value.get('page_size'), str)
            and re.fullmatch(r'[1-9][0-9]{0,2}', value['page_size'])
            and 1 <= int(value['page_size']) <= 100)
    if not valid:
        raise SinkError('invalid_metadata')
    return canonical_json(value)


def _validate_link(payload, record):
    if (set(payload) != {'version_id', 'source_id', 'url', 'captured_at', 'source_field',
                        'capture_origin', 'token_digest'}
            or payload.get('version_id') != record['version_id']
            or type(payload.get('version_id')) is not int
            or payload.get('source_id') != record['source_id']
            or type(payload.get('source_id')) is not int
            or payload.get('source_field') != 'link_personal_auth'
            or payload.get('capture_origin') not in ('individual_detail', 'seed_preflight')
            or not _timestamp(payload.get('captured_at')) or not _sha(payload.get('token_digest'))):
        raise SinkError('invalid_link')
    url = payload.get('url')
    if (not isinstance(url, str) or not 1 <= len(url) <= 8192
            or any(ord(char) < 33 or ord(char) == 127 for char in url)):
        raise SinkError('invalid_link')
    try:
        parts = urlsplit(url)
        if (parts.scheme != 'https' or parts.netloc != 'shop.mv-centr.ru'
                or parts.path != '/personal/auth/secure-login' or parts.fragment):
            raise SinkError('invalid_link')
        pairs = parse_qsl(parts.query, keep_blank_values=True, strict_parsing=True,
                          max_num_fields=8, encoding='utf-8', errors='strict')
        if len(pairs) != 2 or sorted(key for key, _ in pairs) != ['uid', 'vc']:
            raise SinkError('invalid_link')
        query = dict(pairs)
        token = query['vc']
        if (query['uid'] != str(record['source_id']) or not token
                or any(ord(char) < 33 or ord(char) == 127 for char in token)
                or hashlib.sha256(token.encode('utf-8')).hexdigest() != payload['token_digest']):
            raise SinkError('invalid_link')
    except (ValueError, UnicodeError):
        raise SinkError('invalid_link') from None


def _validate_page(payload, record, metadata):
    if (set(payload) != {'version_id', 'module', 'account', 'source', 'resource', 'page',
                        'sha256', 'row_count', 'captured_at', 'parse_code', 'body_b64'}
            or payload.get('version_id') != record['version_id']
            or type(payload.get('version_id')) is not int
            or payload.get('module') != PAGE_FORMAT or payload.get('account') != ACCOUNT
            or payload.get('source') != API_ORIGIN or payload.get('resource') not in RESOURCES
            or not _positive(payload.get('page'))
            or type(payload.get('row_count')) is not int
            or not 0 <= payload['row_count'] <= int(metadata['page_size'])
            or not _sha(payload.get('sha256')) or not _timestamp(payload.get('captured_at'))
            or not isinstance(payload.get('parse_code'), str)
            or not re.fullmatch(r'[a-z][a-z0-9_]{0,63}', payload['parse_code'])):
        raise SinkError('invalid_page')
    packed = _base64(payload.get('body_b64'), MAX_PAYLOAD, 'invalid_page_body')
    try:
        decoder = zlib.decompressobj()
        raw = decoder.decompress(packed, MAX_PAGE_RAW + 1)
        if len(raw) > MAX_PAGE_RAW or decoder.unconsumed_tail:
            raise SinkError('page_too_large')
        if not decoder.eof or decoder.unused_data:
            raise SinkError('invalid_page_body')
    except zlib.error:
        raise SinkError('invalid_page_body') from None
    if hashlib.sha256(raw).hexdigest() != payload['sha256']:
        raise SinkError('payload_hash_mismatch')


def _validate_request(request):
    if (not isinstance(request, dict)
            or set(request) != {'format', 'snapshot', 'kind', 'source_metadata', 'records'}
            or request.get('format') != FORMAT
            or not isinstance(request.get('snapshot'), str)
            or not re.fullmatch(r'[a-f0-9]{32}', request['snapshot'])
            or request.get('kind') not in ('links', 'pages')):
        raise SinkError('invalid_request')
    try:
        if len(canonical_json(request)) > MAX_REQUEST:
            raise SinkError('request_too_large')
    except (ValueError, TypeError, RecursionError):
        raise SinkError('invalid_request') from None
    metadata = _metadata(request['source_metadata'], request['kind'], request['snapshot'])
    records = request['records']
    if type(records) is not list or len(records) > MAX_BATCH:
        raise SinkError('invalid_records')
    seen = set()
    decoded = []
    for item in records:
        if (not isinstance(item, dict)
                or set(item) != {'version_id', 'source_id', 'sha256', 'payload_b64'}
                or not _positive(item.get('version_id')) or item['version_id'] in seen
                or not _sha(item.get('sha256'))
                or (not _positive(item.get('source_id')) if request['kind'] == 'links'
                    else item.get('source_id') is not None)):
            raise SinkError('invalid_records')
        seen.add(item['version_id'])
        raw = _base64(item['payload_b64'], MAX_PAYLOAD)
        if hashlib.sha256(raw).hexdigest() != item['sha256']:
            raise SinkError('payload_hash_mismatch')
        payload = _json(raw)
        if not isinstance(payload, dict):
            raise SinkError('invalid_payload')
        if request['kind'] == 'links':
            _validate_link(payload, item)
        else:
            _validate_page(payload, item, request['source_metadata'])
        decoded.append((item, raw))
    return metadata, decoded


def _private_database(root):
    root = Path(root)
    if root.is_symlink():
        raise SinkError('private_storage_required')
    # Python 3.13 applies special Windows ACL handling to 0700. This receiver is
    # deployed on Linux; Windows executes only synthetic injected-root tests.
    root.mkdir(mode=0o700 if os.name != 'nt' else 0o777, exist_ok=True)
    info = root.stat()
    if not stat.S_ISDIR(info.st_mode) or (hasattr(os, 'getuid') and info.st_uid != os.getuid()):
        raise SinkError('private_storage_required')
    if os.name != 'nt':
        os.chmod(root, 0o700)
    path = root / 'archive.sqlite'
    for candidate in (path, *(root / ('archive.sqlite' + suffix) for suffix in ('-journal', '-wal', '-shm'))):
        if candidate.is_symlink() or (candidate.exists() and (
                not candidate.is_file() or candidate.stat().st_nlink != 1)):
            raise SinkError('private_storage_required')
    descriptor = os.open(path, os.O_RDWR | os.O_CREAT | getattr(os, 'O_NOFOLLOW', 0), 0o600)
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise SinkError('private_storage_required')
        if os.name != 'nt':
            os.chmod(path, 0o600)
    finally:
        os.close(descriptor)
    return path


def _open(path):
    db = sqlite3.connect(path, timeout=5)
    try:
        db.execute('PRAGMA busy_timeout=5000')
        db.execute('PRAGMA synchronous=FULL')
        db.execute('PRAGMA foreign_keys=ON')
        existing = {row[0] for row in db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}
        if existing and existing != {'archive_metadata', 'source_metadata', 'records'}:
            raise SinkError('invalid_archive')
        db.executescript('''
            CREATE TABLE IF NOT EXISTS archive_metadata (key TEXT PRIMARY KEY,value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS source_metadata (
                snapshot TEXT NOT NULL,kind TEXT NOT NULL,metadata_json TEXT NOT NULL,
                PRIMARY KEY(snapshot,kind));
            CREATE TABLE IF NOT EXISTS records (
                snapshot TEXT NOT NULL,kind TEXT NOT NULL,version_id INTEGER NOT NULL,
                source_id INTEGER,sha256 TEXT NOT NULL,payload_encrypted BLOB NOT NULL,
                received_at TEXT NOT NULL,PRIMARY KEY(snapshot,kind,version_id),
                FOREIGN KEY(snapshot,kind) REFERENCES source_metadata(snapshot,kind));
        ''')
        expected = {'format': FORMAT, 'site': SITE}
        actual = dict(db.execute('SELECT key,value FROM archive_metadata'))
        if actual and actual != expected:
            raise SinkError('invalid_archive')
        if not actual:
            with db:
                db.executemany('INSERT INTO archive_metadata VALUES (?,?)', expected.items())
        return db
    except BaseException:
        db.close()
        raise


def _envelope(request, item, raw, metadata):
    return {'format': FORMAT, 'site': SITE, 'snapshot': request['snapshot'],
        'kind': request['kind'], 'version_id': item['version_id'],
        'source_id': item['source_id'], 'sha256': item['sha256'],
        'source_metadata_sha256': hashlib.sha256(metadata).hexdigest(),
        'payload_b64': base64.b64encode(raw).decode('ascii')}


def _read_back(path, request, decoded, metadata, cipher):
    try:
        # A new connection proves the commit, rather than reading pending writes.
        with closing(sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True)) as db:
            db.execute('PRAGMA query_only=ON')
            for item, raw in decoded:
                row = db.execute('''SELECT source_id,sha256,payload_encrypted FROM records
                    WHERE snapshot=? AND kind=? AND version_id=?''',
                    (request['snapshot'], request['kind'], item['version_id'])).fetchone()
                if not row or row[:2] != (item['source_id'], item['sha256']):
                    raise SinkError('readback_failed')
                envelope = _json(cipher.decrypt(row[2]))
                if envelope != _envelope(request, item, raw, metadata):
                    raise SinkError('readback_failed')
                restored = _base64(envelope.get('payload_b64'), MAX_PAYLOAD)
                if hashlib.sha256(restored).hexdigest() != item['sha256']:
                    raise SinkError('readback_failed')
            return db.execute('SELECT COUNT(*) FROM records WHERE snapshot=? AND kind=?',
                              (request['snapshot'], request['kind'])).fetchone()[0]
    except Exception:
        raise SinkError('readback_failed') from None


def handle_request(request, *, root, cipher):
    """Persist/verify a bounded batch; callers may discard local data only on ACK."""
    try:
        metadata, decoded = _validate_request(request)
        path = _private_database(root)
        with closing(_open(path)) as db:
            try:
                db.execute('BEGIN IMMEDIATE')
                row = db.execute('SELECT metadata_json FROM source_metadata WHERE snapshot=? AND kind=?',
                                 (request['snapshot'], request['kind'])).fetchone()
                if row and row[0] != metadata.decode('ascii'):
                    raise SinkError('source_metadata_conflict')
                if not row:
                    db.execute('INSERT INTO source_metadata VALUES (?,?,?)',
                               (request['snapshot'], request['kind'], metadata.decode('ascii')))
                for item, raw in decoded:
                    previous = db.execute('''SELECT source_id,sha256 FROM records
                        WHERE snapshot=? AND kind=? AND version_id=?''',
                        (request['snapshot'], request['kind'], item['version_id'])).fetchone()
                    if previous is not None:
                        if previous != (item['source_id'], item['sha256']):
                            raise SinkError('version_conflict')
                        continue
                    encrypted = cipher.encrypt(canonical_json(_envelope(request, item, raw, metadata)))
                    if not isinstance(encrypted, bytes) or not encrypted:
                        raise SinkError('archive_failed')
                    db.execute('INSERT INTO records VALUES (?,?,?,?,?,?,?)',
                        (request['snapshot'], request['kind'], item['version_id'], item['source_id'],
                         item['sha256'], encrypted, datetime.now(timezone.utc).isoformat()))
                db.commit()
            except BaseException:
                db.rollback()
                raise
        total = _read_back(path, request, decoded, metadata, cipher)
        return {'format': FORMAT, 'site': SITE, 'snapshot': request['snapshot'],
            'kind': request['kind'], 'records': [
                {name: item[name] for name in ('version_id', 'source_id', 'sha256')}
                for item, _ in decoded], 'stored_total': total}
    except SinkError:
        raise
    except sqlite3.Error as error:
        code = getattr(error, 'sqlite_errorcode', None)
        raise SinkError('archive_busy' if code in (sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED)
                        else 'archive_failed') from None
    except Exception:
        raise SinkError('archive_failed') from None


def runtime_archive():
    """Read the EXISTING MVC site key; never create or print one."""
    import frappe
    from cryptography.fernet import Fernet
    frappe.init(site=SITE)
    try:
        if str(frappe.local.site) != SITE:
            raise SinkError('wrong_site')
        key = frappe.conf.get('encryption_key')
        if not isinstance(key, (str, bytes)) or not key:
            raise SinkError('existing_site_key_required')
        try:
            cipher = Fernet(key.encode('ascii') if isinstance(key, str) else key)
        except (ValueError, UnicodeError):
            raise SinkError('existing_site_key_required') from None
        return Path(frappe.get_site_path('private', 'avo-ingest')), cipher
    finally:
        frappe.destroy()


def main():
    try:
        raw = sys.stdin.buffer.read(MAX_REQUEST + 1)
        if len(raw) > MAX_REQUEST:
            raise SinkError('request_too_large')
        request = _json(raw)
        root, cipher = runtime_archive()
        response = handle_request(request, root=root, cipher=cipher)
        result = 0
    except Exception as error:
        code = str(error) if isinstance(error, SinkError) and str(error) in SAFE_CODES else 'archive_failed'
        response, result = {'format': FORMAT, 'error': code}, 2
    print(json.dumps(response, ensure_ascii=True, sort_keys=True))
    return result


if __name__ == '__main__':
    raise SystemExit(main())

"""Read a completed MV/IOMP contacts resource while other exports keep running.

No Frappe, source-key, network or write operation exists here. The caller passes
the selected site's existing Fernet cipher. Every SELECT finishes before a page
is decrypted or yielded, because the producer's SQLite journal is not WAL.
"""
import base64
from contextlib import closing
from datetime import datetime
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import zlib

from server_archive_sink import PROFILES


MAX_BODY = 16 * 1024 * 1024
MAX_PAGE_ENVELOPE = 24 * 1024 * 1024
MAX_STORAGE_ENVELOPE = 34 * 1024 * 1024
MAX_CIPHERTEXT = 48 * 1024 * 1024
PAGE_COLUMNS = ('version_id', 'module', 'account', 'source', 'resource', 'page',
                'sha256', 'row_count', 'captured_at', 'parse_code', 'raw_encrypted')


class ContactReadError(Exception):
    """Fixed error codes only; no source values or exception strings."""


def _positive(value):
    return type(value) is int and 0 < value < 2**63


def _sha(value):
    return isinstance(value, str) and re.fullmatch(r'[a-f0-9]{64}', value) is not None


def _identifier(value):
    if _positive(value):
        return str(value)
    if type(value) is str and re.fullmatch(r'[1-9][0-9]{0,18}', value) and int(value) < 2**63:
        return value
    raise ContactReadError('invalid_contact_id')


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ContactReadError('invalid_json')
        result[key] = value
    return result


def _constant(value):
    raise ContactReadError('invalid_json')


def _json(raw, *, bom=False):
    try:
        return json.loads(raw.decode('utf-8-sig' if bom else 'utf-8'),
                          object_pairs_hook=_pairs, parse_constant=_constant)
    except (ValueError, TypeError, UnicodeError, RecursionError):
        raise ContactReadError('invalid_json') from None


def _base64(value, maximum):
    if not isinstance(value, str) or len(value) > (maximum + 2) // 3 * 4:
        raise ContactReadError('payload_too_large')
    try:
        raw = base64.b64decode(value, validate=True)
    except (ValueError, UnicodeError):
        raise ContactReadError('invalid_base64') from None
    if len(raw) > maximum:
        raise ContactReadError('payload_too_large')
    return raw


def _decompress(packed, maximum):
    try:
        decoder = zlib.decompressobj()
        raw = decoder.decompress(packed, maximum + 1)
        if len(raw) > maximum or decoder.unconsumed_tail:
            raise ContactReadError('payload_too_large')
        if not decoder.eof or decoder.unused_data:
            raise ContactReadError('invalid_compression')
        return raw
    except zlib.error:
        raise ContactReadError('invalid_compression') from None


def _query(db, sql, values=()):
    with closing(db.execute(sql, values)) as cursor:
        return cursor.fetchall()


def _one(db, sql, values=()):
    rows = _query(db, sql, values)
    if len(rows) != 1:
        raise ContactReadError('invalid_archive')
    return rows[0]


def _metadata(db, profile):
    metadata = dict(_query(db, 'SELECT key,value FROM metadata'))
    if (set(metadata) != {'format', 'account', 'source', 'page_size', 'snapshot'}
            or metadata.get('format') != profile.page_format or metadata.get('account') != profile.account
            or metadata.get('source') != profile.api_origin
            or type(metadata.get('snapshot')) is not str
            or not re.fullmatch(r'[a-f0-9]{32}', metadata['snapshot'])
            or type(metadata.get('page_size')) is not str
            or not re.fullmatch(r'[1-9][0-9]{0,2}', metadata['page_size'])
            or not 1 <= int(metadata['page_size']) <= 100):
        raise ContactReadError('source_identity_mismatch')
    return metadata


def _state(db):
    state = _one(db, "SELECT next_page,row_count,status,error_code FROM resource_state WHERE resource='contacts'")
    page, count, status, error = state
    if (not _positive(page) or not _positive(count) or status != 'complete' or error is not None):
        raise ContactReadError('contacts_not_complete')
    return state


def _page_key(profile, page):
    raw = (profile.page_format + ':contacts:' + str(page)).encode()
    return int.from_bytes(hashlib.sha256(raw).digest()[:8], 'big') % (2**63 - 1) + 1


def _timestamp(value):
    if not isinstance(value, str) or not 1 <= len(value) <= 80:
        return False
    try:
        date = datetime.fromisoformat(value)
        return date.tzinfo is not None and date.utcoffset() is not None
    except ValueError:
        return False


def _decode(row, cipher, profile, metadata):
    value = dict(zip(PAGE_COLUMNS, row))
    if (not _positive(value['version_id']) or value['module'] != profile.page_format
            or value['account'] != profile.account or value['source'] != profile.api_origin
            or value['resource'] != 'contacts' or type(value['page']) is not int
            or not 0 <= value['page'] < 2**63 or not _sha(value['sha256'])
            or type(value['row_count']) is not int
            or not 0 <= value['row_count'] <= int(metadata['page_size'])
            or not _timestamp(value['captured_at'])
            or not isinstance(value['raw_encrypted'], bytes)
            or not 1 <= len(value['raw_encrypted']) <= MAX_CIPHERTEXT):
        raise ContactReadError('invalid_page')
    try:
        storage_raw = cipher.decrypt(value['raw_encrypted'])
    except Exception:
        raise ContactReadError('source_crypto_failed') from None
    if not isinstance(storage_raw, bytes) or len(storage_raw) > MAX_STORAGE_ENVELOPE:
        raise ContactReadError('payload_too_large')
    storage = _json(storage_raw)
    binding = {'format': 'avo-server-private-storage-v1', 'account': profile.account,
               'namespace': profile.crypto_namespace, 'source_id': _page_key(profile, value['page'])}
    if (not isinstance(storage, dict) or set(storage) != set(binding) | {'data_b64'}
            or any(storage.get(key) != expected for key, expected in binding.items())
            or type(storage.get('source_id')) is not int):
        raise ContactReadError('storage_identity_mismatch')
    packed = _base64(storage['data_b64'], MAX_PAGE_ENVELOPE)
    envelope = _json(_decompress(packed, MAX_PAGE_ENVELOPE))
    expected = {'format': profile.page_format, 'account': profile.account, 'source': profile.api_origin,
                'resource': 'contacts', 'page': value['page'], 'snapshot': metadata['snapshot'],
                'sha256': value['sha256']}
    if (not isinstance(envelope, dict) or set(envelope) != set(expected) | {'body'}
            or any(envelope.get(key) != wanted for key, wanted in expected.items())
            or type(envelope.get('page')) is not int):
        raise ContactReadError('page_identity_mismatch')
    raw = _base64(envelope['body'], MAX_BODY)
    if hashlib.sha256(raw).hexdigest() != value['sha256']:
        raise ContactReadError('page_hash_mismatch')
    return value, raw


def _empty(value):
    html = re.fullmatch(r'No items where found for model\s+<b>([A-Za-z][A-Za-z0-9_]*)?</b>', value)
    if html:
        model = html.group(1)
        if model and model.casefold() not in ('contact', 'contacts'):
            raise ContactReadError('invalid_terminal_marker')
        return True
    text = re.fullmatch(r'No items where found for model(?:(?:\s*:\s*|\s+)([A-Za-z][A-Za-z0-9_]*))?\s*', value)
    if text:
        if text.group(1) and text.group(1).casefold() not in ('contact', 'contacts'):
            raise ContactReadError('invalid_terminal_marker')
        return True
    return False


def _rows(raw, profile):
    try:
        text = raw.decode('utf-8-sig').strip()
    except UnicodeError:
        raise ContactReadError('invalid_json') from None
    if _empty(text):
        return []
    value = _json(raw, bom=True)
    for _ in range(4):
        if isinstance(value, str) and _empty(value):
            return []
        if type(value) is list and all(type(row) is dict for row in value):
            return value
        if type(value) is dict:
            if value.get('error') or value.get('errors'):
                break
            if 'source' in value and value['source'] != profile.api_origin:
                raise ContactReadError('source_identity_mismatch')
            if 'id_contact' in value:
                return [value]
            containers = [value[key] for key in ('data', 'items', 'contacts') if key in value]
            if len(containers) == 1:
                value = containers[0]
                continue
        break
    raise ContactReadError('unexpected_contact_structure')


def _ids_fingerprint(db, profile, *, index):
    last, count = 0, 0
    fingerprint = hashlib.sha256(profile.api_origin.encode('ascii'))
    while True:
        if index:
            rows = _query(db, 'SELECT id,record_json FROM contacts WHERE id>? ORDER BY id LIMIT 1000', (last,))
        else:
            rows = _query(db, "SELECT source_id FROM row_ids WHERE resource='contacts' AND source_id>? ORDER BY source_id LIMIT 1000", (last,))
        if not rows:
            return count, fingerprint.hexdigest()
        for row in rows:
            ident = _identifier(row[0])
            if int(ident) <= last:
                raise ContactReadError('invalid_source_index')
            if index:
                if not isinstance(row[1], str) or len(row[1]) > 4096:
                    raise ContactReadError('invalid_source_index')
                record = _json(row[1].encode())
                if (type(record) is not dict or set(record) != {'source', 'contact'}
                        or record['source'] != profile.api_origin or type(record['contact']) is not dict
                        or set(record['contact']) != {'id'}
                        or _identifier(record['contact']['id']) != ident):
                    raise ContactReadError('invalid_source_index')
            last = int(ident)
            count += 1
            fingerprint.update(ident.encode('ascii') + b'\n')


def _connect(path):
    path = Path(path)
    if not path.is_file() or path.is_symlink() or path.stat().st_nlink != 1:
        raise ContactReadError('unsafe_source_path')
    db = sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True, timeout=2)
    db.execute('PRAGMA query_only=ON')
    db.execute('PRAGMA cache_size=-2048')
    db.execute('PRAGMA mmap_size=0')
    return db


def iter_contacts(job_path, cipher, account):
    """Yield canonical-ID contact dictionaries after a resource-completeness gate.

    Full consumption checks every accepted page and both saved ID fingerprints.
    A caller must complete a validation pass before starting production writes.
    Other resource pages are neither read nor required to have completed.
    """
    try:
        if account not in ('mastervision', 'iomp'):
            raise ContactReadError('wrong_account')
        profile = PROFILES[account]
        job = Path(job_path)
        if job.is_symlink():
            raise ContactReadError('unsafe_source_path')
        with closing(_connect(job / 'snapshot.sqlite')) as db, closing(_connect(job / 'contacts.sqlite')) as index:
            metadata = _metadata(db, profile)
            state = _state(db)
            next_page, expected_count = state[:2]
            summary = _one(db, """SELECT COUNT(*),COUNT(DISTINCT page),COALESCE(SUM(row_count),0),
                MIN(page),MAX(page) FROM pages WHERE resource='contacts' AND parse_code='accepted'""")
            if summary != (next_page, next_page, expected_count, 0, next_page - 1):
                raise ContactReadError('incomplete_contact_pages')
            columns = ','.join(PAGE_COLUMNS)
            terminal_rows = _query(db, 'SELECT ' + columns +
                " FROM pages WHERE resource='contacts' AND page=? ORDER BY version_id DESC LIMIT 1", (next_page,))
            if not terminal_rows:
                raise ContactReadError('terminal_marker_missing')
            terminal, terminal_raw = _decode(terminal_rows[0], cipher, profile, metadata)
            if (terminal['parse_code'] not in ('complete', 'invalid_json') or terminal['row_count']
                    or _rows(terminal_raw, profile) != []):
                raise ContactReadError('invalid_terminal_marker')
            if (_one(index, 'SELECT COUNT(*) FROM contacts')[0] != expected_count
                    or _one(db, "SELECT COUNT(*) FROM row_ids WHERE resource='contacts'")[0] != expected_count):
                raise ContactReadError('source_index_mismatch')
            index_count, index_hash = _ids_fingerprint(index, profile, index=True)
            ids_count, ids_hash = _ids_fingerprint(db, profile, index=False)
            if index_count != expected_count or ids_count != expected_count or index_hash != ids_hash:
                raise ContactReadError('source_index_mismatch')
            fingerprint = hashlib.sha256(profile.api_origin.encode('ascii'))
            count, last_id = 0, 0
            for page in range(next_page):
                candidates = _query(db, 'SELECT ' + columns +
                    " FROM pages WHERE resource='contacts' AND page=? AND parse_code='accepted' LIMIT 2", (page,))
                if len(candidates) != 1:
                    raise ContactReadError('incomplete_contact_pages')
                saved, raw = _decode(candidates[0], cipher, profile, metadata)
                rows = _rows(raw, profile)
                if not rows or len(rows) != saved['row_count']:
                    raise ContactReadError('contact_page_count_mismatch')
                safe_rows = []
                for row in rows:
                    ident = _identifier(row.get('id_contact'))
                    if int(ident) <= last_id:
                        raise ContactReadError('source_id_order')
                    last_id = int(ident)
                    count += 1
                    fingerprint.update(ident.encode('ascii') + b'\n')
                    safe = dict(row, id_contact=ident)
                    safe.pop('link_personal_auth', None)
                    safe_rows.append(safe)
                for row in safe_rows:
                    yield row
            if count != expected_count or fingerprint.hexdigest() != index_hash:
                raise ContactReadError('source_fingerprint_mismatch')
            if _metadata(db, profile) != metadata or _state(db) != state:
                raise ContactReadError('source_changed')
    except ContactReadError:
        raise
    except sqlite3.Error as error:
        code = getattr(error, 'sqlite_errorcode', None)
        raise ContactReadError('source_busy' if code in (sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED)
                               else 'source_read_failed') from None
    except Exception:
        raise ContactReadError('source_read_failed') from None

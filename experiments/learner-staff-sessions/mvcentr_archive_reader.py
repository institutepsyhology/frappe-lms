"""Read verified MVC contact pages from its completed encrypted server vault.

This module has no Frappe, network or write path. List-returned personal links
are deliberately removed: only the separately verified individual-link archive
may supply those credentials to a future login implementation.
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


SITE = 'my-lk.mv-centr.ru'
ACCOUNT = 'mv-centr'
API_ORIGIN = 'https://mvcentr.autoweboffice.ru'
FORMAT = 'mvc-frappe-archive-v1'
PAGE_FORMAT = 'mvcentr-legacy-api-snapshot-v1'
LINK_SCHEMA = 'mvcentr-individual-links-v1'
MAX_BODY = 16 * 1024 * 1024
MAX_PAYLOAD = 20 * 1024 * 1024
MAX_ENVELOPE = 28 * 1024 * 1024
MAX_ENCRYPTED = 40 * 1024 * 1024
RESOURCES = frozenset(('contacts', 'employee', 'training', 'trainingAccess', 'accounts',
    'accountline', 'goods', 'ContactRecurringPayments', 'newsletter', 'contactnewsletterlinks',
    'contacttaglnk', 'telegrambotcontactlnk', 'funnelcontact', 'organization', 'costs',
    'costsarticle', 'goodscategory', 'goodscolor', 'goodssize', 'callcenterrequest',
    'mainsettings', 'partner', 'goodspincodes', 'advertisingchannelcompany',
    'advertisingchannel', 'advertisingchannelstatistics'))


class ReaderError(Exception):
    """Arguments are fixed codes and never contain a contact, URL or password."""


def _canonical(value):
    return json.dumps(value, ensure_ascii=True, sort_keys=True,
                      separators=(',', ':'), allow_nan=False).encode('ascii')


def _pairs(items):
    result = {}
    for key, value in items:
        if key in result:
            raise ReaderError('invalid_json')
        result[key] = value
    return result


def _constant(value):
    raise ReaderError('invalid_json')


def _json(raw, *, bom=False):
    try:
        return json.loads(raw.decode('utf-8-sig' if bom else 'utf-8'),
                          object_pairs_hook=_pairs, parse_constant=_constant)
    except (ValueError, TypeError, UnicodeError, RecursionError):
        raise ReaderError('invalid_json') from None


def _sha(value):
    return isinstance(value, str) and re.fullmatch(r'[a-f0-9]{64}', value) is not None


def _positive(value):
    return type(value) is int and 0 < value < 2**63


def _timestamp(value):
    if not isinstance(value, str) or not 1 <= len(value) <= 80:
        return False
    try:
        parsed = datetime.fromisoformat(value)
        return parsed.tzinfo is not None and parsed.utcoffset() is not None
    except ValueError:
        return False


def _source_id(value):
    if type(value) is int and _positive(value):
        return str(value)
    if (type(value) is str and re.fullmatch(r'[1-9][0-9]{0,18}', value)
            and int(value) < 2**63):
        return value
    raise ReaderError('invalid_contact_id')


def _b64(value, maximum):
    if not isinstance(value, str) or len(value) > (maximum + 2) // 3 * 4:
        raise ReaderError('payload_too_large')
    try:
        raw = base64.b64decode(value, validate=True)
    except (ValueError, UnicodeError):
        raise ReaderError('invalid_base64') from None
    if len(raw) > maximum:
        raise ReaderError('payload_too_large')
    return raw


def _metadata(db, snapshot, kind):
    row = db.execute('SELECT metadata_json FROM source_metadata WHERE snapshot=? AND kind=?',
                     (snapshot, kind)).fetchone()
    if not row or not isinstance(row[0], str) or len(row[0]) > 4096:
        raise ReaderError('invalid_metadata')
    metadata = _json(row[0].encode('utf-8'))
    if not isinstance(metadata, dict) or _canonical(metadata).decode('ascii') != row[0]:
        raise ReaderError('invalid_metadata')
    if kind == 'pages':
        valid = (set(metadata) == {'format', 'account', 'source', 'page_size', 'snapshot'}
            and metadata.get('format') == PAGE_FORMAT and metadata.get('account') == ACCOUNT
            and metadata.get('source') == API_ORIGIN and metadata.get('snapshot') == snapshot
            and type(metadata.get('page_size')) is str
            and re.fullmatch(r'[1-9][0-9]{0,2}', metadata['page_size'])
            and 1 <= int(metadata['page_size']) <= 100)
    else:
        valid = (set(metadata) == {'schema', 'account', 'origin', 'source_ids_sha256', 'source_count'}
            and metadata.get('schema') == LINK_SCHEMA and metadata.get('account') == ACCOUNT
            and metadata.get('origin') == API_ORIGIN and _sha(metadata.get('source_ids_sha256'))
            and type(metadata.get('source_count')) is str
            and re.fullmatch(r'[1-9][0-9]{0,18}', metadata['source_count'])
            and int(metadata['source_count']) < 2**63)
    if not valid:
        raise ReaderError('invalid_metadata')
    return metadata


def _page(row, cipher, snapshot, metadata_hash, page_size):
    version, source_id, digest, encrypted = row
    if (not _positive(version) or source_id is not None or not _sha(digest)
            or not isinstance(encrypted, bytes) or not 1 <= len(encrypted) <= MAX_ENCRYPTED):
        raise ReaderError('invalid_record')
    try:
        raw_envelope = cipher.decrypt(encrypted)
    except Exception:
        raise ReaderError('archive_crypto_failed') from None
    if not isinstance(raw_envelope, bytes) or len(raw_envelope) > MAX_ENVELOPE:
        raise ReaderError('payload_too_large')
    envelope = _json(raw_envelope)
    binding = {'format': FORMAT, 'site': SITE, 'snapshot': snapshot, 'kind': 'pages',
        'version_id': version, 'source_id': None, 'sha256': digest,
        'source_metadata_sha256': metadata_hash}
    if (not isinstance(envelope, dict) or set(envelope) != set(binding) | {'payload_b64'}
            or any(envelope.get(key) != value for key, value in binding.items())
            or type(envelope.get('version_id')) is not int):
        raise ReaderError('invalid_envelope')
    raw_payload = _b64(envelope['payload_b64'], MAX_PAYLOAD)
    if hashlib.sha256(raw_payload).hexdigest() != digest:
        raise ReaderError('payload_hash_mismatch')
    payload = _json(raw_payload)
    if (not isinstance(payload, dict)
            or set(payload) != {'version_id', 'module', 'account', 'source', 'resource', 'page',
                                'sha256', 'row_count', 'captured_at', 'parse_code', 'body_b64'}
            or type(payload.get('version_id')) is not int or payload['version_id'] != version
            or payload.get('module') != PAGE_FORMAT or payload.get('account') != ACCOUNT
            or payload.get('source') != API_ORIGIN or payload.get('resource') not in RESOURCES
            or type(payload.get('page')) is not int or not 0 <= payload['page'] < 2**63
            or type(payload.get('row_count')) is not int or not 0 <= payload['row_count'] <= page_size
            or not _sha(payload.get('sha256'))
            or not _timestamp(payload.get('captured_at'))
            or not isinstance(payload.get('parse_code'), str)
            or not re.fullmatch(r'[a-z][a-z0-9_]{0,63}', payload['parse_code'])):
        raise ReaderError('invalid_page')
    packed = _b64(payload['body_b64'], MAX_PAYLOAD)
    try:
        decoder = zlib.decompressobj()
        body = decoder.decompress(packed, MAX_BODY + 1)
        if len(body) > MAX_BODY or decoder.unconsumed_tail:
            raise ReaderError('page_too_large')
        if not decoder.eof or decoder.unused_data:
            raise ReaderError('invalid_page_body')
    except zlib.error:
        raise ReaderError('invalid_page_body') from None
    if hashlib.sha256(body).hexdigest() != payload['sha256']:
        raise ReaderError('page_hash_mismatch')
    return payload, body


def _contact_rows(raw):
    value = _json(raw, bom=True)
    for _ in range(4):
        if type(value) is list and all(type(item) is dict for item in value):
            return value
        if type(value) is dict:
            if value.get('error') or value.get('errors'):
                break
            if 'source' in value and value['source'] != API_ORIGIN:
                raise ReaderError('wrong_source')
            if 'id_contact' in value:
                return [value]
            containers = [value[name] for name in ('data', 'items', 'contacts') if name in value]
            if len(containers) == 1:
                value = containers[0]
                continue
        break
    raise ReaderError('invalid_contact_structure')


def iter_contacts(database_path, cipher, snapshot):
    """Yield (page_version_id, raw contact), verifying completed source coverage.

    IDs normalize to canonical decimal strings. Every other source value is
    preserved exactly except the untrusted list-returned personal login URL.
    Final count/fingerprint checks require consuming the iterator to its end.
    """
    try:
        if not isinstance(snapshot, str) or not re.fullmatch(r'[a-f0-9]{32}', snapshot):
            raise ReaderError('invalid_snapshot')
        path = Path(database_path)
        if not path.is_file() or path.is_symlink() or path.stat().st_nlink != 1:
            raise ReaderError('invalid_archive')
        with closing(sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True, timeout=5)) as db:
            db.execute('PRAGMA query_only=ON')
            db.execute('PRAGMA cache_size=-2048')
            db.execute('PRAGMA mmap_size=0')
            if dict(db.execute('SELECT key,value FROM archive_metadata')) != {'format': FORMAT, 'site': SITE}:
                raise ReaderError('wrong_source')
            pages_meta = _metadata(db, snapshot, 'pages')
            links_meta = _metadata(db, snapshot, 'links')
            metadata_hash = hashlib.sha256(_canonical(pages_meta)).hexdigest()
            expected_count = int(links_meta['source_count'])
            fingerprint = hashlib.sha256(API_ORIGIN.encode('ascii'))
            last_version, next_page, count, last_id = 0, 0, 0, 0
            while True:
                # End each SELECT before yielding to the caller or decrypting a
                # page, so a long app write does not pin a vault read cursor.
                with closing(db.execute('''SELECT version_id,source_id,sha256,payload_encrypted
                    FROM records WHERE snapshot=? AND kind='pages' AND version_id>?
                    ORDER BY version_id LIMIT 1''', (snapshot, last_version))) as cursor:
                    row = cursor.fetchone()
                if row is None:
                    break
                payload, body = _page(row, cipher, snapshot, metadata_hash, int(pages_meta['page_size']))
                last_version = row[0]
                if payload['resource'] != 'contacts' or payload['parse_code'] != 'accepted':
                    continue
                if payload['page'] != next_page:
                    raise ReaderError('contact_page_sequence')
                rows = _contact_rows(body)
                if not rows or len(rows) != payload['row_count'] or len(rows) > int(pages_meta['page_size']):
                    raise ReaderError('contact_page_count')
                safe_rows = []
                for raw in rows:
                    ident = _source_id(raw.get('id_contact'))
                    if int(ident) <= last_id:
                        raise ReaderError('contact_id_order')
                    last_id = int(ident)
                    count += 1
                    if count > expected_count:
                        raise ReaderError('source_count_mismatch')
                    fingerprint.update(ident.encode('ascii') + b'\n')
                    safe = dict(raw, id_contact=ident)
                    safe.pop('link_personal_auth', None)
                    safe_rows.append(safe)
                next_page += 1
                for raw in safe_rows:
                    yield row[0], raw
            if not next_page or count != expected_count:
                raise ReaderError('source_count_mismatch')
            if fingerprint.hexdigest() != links_meta['source_ids_sha256']:
                raise ReaderError('source_fingerprint_mismatch')
    except ReaderError:
        raise
    except Exception:
        raise ReaderError('archive_read_failed') from None

"""Private resumable READ-ONLY legacy API archive for MV-Centr, not all AVO data.

Run with --output-directory OUTSIDE any Git repository. One masked local window
accepts API KEY GET; no key CLI/environment option, login, write API or Frappe
mutation exists. Raw replies are compressed and encrypted with current-user
Windows DPAPI. contacts.sqlite contains only source IDs for the separate link
collector. List-returned personal links are archived but NEVER trusted for login.
"""
from __future__ import annotations

import argparse
import base64
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import hashlib
from http.client import HTTPException
import json
import math
import os
from pathlib import Path
import queue
import re
import sqlite3
import threading
import time
from urllib.error import HTTPError, URLError
from urllib.parse import unquote, urlencode
from urllib.request import ProxyHandler, Request, build_opener
import uuid
import zlib

from audit_legacy_links import API_ORIGIN
from collect_personal_links import NoRedirect, parse_key
from collect_personal_links_bulk import writer_lock
from private_link_storage import _crypt
from progress_io import ProgressWriteError, read_json, write_json
from server_archive_sink import PROFILE


ACCOUNT = PROFILE.account
FORMAT = PROFILE.page_format
MAX_BODY = 16 * 1024 * 1024
FAILURE_LIMIT = 10
GAPS = ['positions_and_permission_matrices', 'full_lesson_builder_contents',
        'homework_and_progress', 'complete_message_and_marketing_history']


@dataclass(frozen=True)
class Resource:
    name: str
    id_field: str | None


# Exact legacy names from official API reference / AutoWebOffice/AwoApi.
# None means the official SDK names the endpoint but does not document its PK:
# archive it without guessing fields or promising ID-level completeness.
RESOURCES = tuple(Resource(*item) for item in (
    ('contacts', 'id_contact'), ('employee', 'id_employee'), ('training', 'id_training'),
    ('trainingAccess', None), ('accounts', 'id_account'), ('accountline', 'id_account_line'),
    ('goods', 'id_goods'), ('ContactRecurringPayments', 'id_contact_recurring_payments'),
    ('newsletter', 'id_newsletter'), ('contactnewsletterlinks', 'id_contact_newsletter_links'),
    ('contacttaglnk', None), ('telegrambotcontactlnk', None), ('funnelcontact', None),
    ('organization', 'id_organization'), ('costs', 'id_costs'), ('costsarticle', 'id_costs_article'),
    ('goodscategory', 'id_goods_category'), ('goodscolor', 'id_goods_color'),
    ('goodssize', 'id_goods_size'), ('callcenterrequest', 'id_callcenter_request'),
    ('mainsettings', 'id_stores'), ('partner', None), ('goodspincodes', None),
    ('advertisingchannelcompany', None), ('advertisingchannel', None),
    ('advertisingchannelstatistics', None)))
INVENTORY = {item.name: item for item in RESOURCES}
LINK_STATUSES = frozenset({'completed', 'completed_with_failures', 'cancelled',
    'stopped_fatal_error', 'stopped_consecutive_failures', 'collecting', 'retry_wait', 'initializing'})
CODES = frozenset({'invalid_arguments', 'wrong_account', 'private_output_required',
    'invalid_archive', 'archive_metadata_mismatch', 'network_error', 'redirect_blocked',
    'response_too_large', 'unexpected_structure', 'invalid_json', 'invalid_id',
    'duplicate_ids', 'repeated_page', 'page_too_large', 'api_key_in_response',
    'encoding_too_deep', 'wrong_source', 'failure_limit', 'cancelled',
    'retry_after_excessive', 'internal_failure', 'private_storage_failed',
    'invalid_key_input', 'collector_already_running', 'link_collection_failed', 'resource_errors',
    'unverifiable_encoding'})


class SnapshotError(Exception):
    pass


@dataclass(frozen=True)
class Response:
    status: int
    body: bytes
    retry_after: str | None = None


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec='microseconds')


def safe_code(error):
    if isinstance(error, ProgressWriteError):
        return 'progress_file_locked'
    code = error.args[0] if len(error.args) == 1 else None
    return code if isinstance(code, str) and (code in CODES or re.fullmatch(r'http_[1-5]\d\d', code)) else 'internal_failure'


def read_page(key, resource, page, size, sort):
    if resource not in INVENTORY:
        raise SnapshotError('invalid_arguments')
    parameters = {'r': 'api/rest/' + resource, 'key': key,
                  'param[pagesize]': size, 'param[currentpage]': page}
    if sort:
        parameters['param[sort]'] = sort
    url = API_ORIGIN + '/?' + urlencode(parameters)
    request = Request(url, headers={'Accept': 'application/json'}, method='GET')
    try:
        try:
            stream = build_opener(ProxyHandler({}), NoRedirect()).open(request, timeout=20)
        except HTTPError as error:
            stream = error
        with stream:
            if stream.geturl() != url or 300 <= stream.code < 400:
                raise SnapshotError('redirect_blocked')
            body = stream.read(MAX_BODY + 1)
            status, retry = stream.code, stream.headers.get('Retry-After')
        if len(body) > MAX_BODY:
            raise SnapshotError('response_too_large')
        return Response(status, body, retry)
    except (URLError, TimeoutError, OSError, HTTPException):
        raise SnapshotError('network_error') from None


def reject_key_leak(raw, key):
    """Inspect raw and decoded JSON strings; persist neither key nor its URL forms."""
    try:
        text = raw.decode('utf-8-sig')
    except UnicodeError:
        # An undecodable body cannot be checked for encoded credentials.
        raise SnapshotError('unverifiable_encoding') from None
    try:
        payload = json.loads(text)
    except ValueError:
        payload = None
    pending = [text, payload]
    key_forms = {key}
    for _ in range(16):
        newer = {unquote(value) for value in key_forms}
        if newer <= key_forms:
            break
        key_forms |= newer
    else:
        raise SnapshotError('encoding_too_deep')
    while pending:
        value = pending.pop()
        if isinstance(value, dict):
            pending.extend(value.keys())
            pending.extend(value.values())
        elif isinstance(value, list):
            pending.extend(value)
        elif isinstance(value, str):
            for _ in range(16):
                if any(secret and secret in value for secret in key_forms):
                    raise SnapshotError('api_key_in_response')
                decoded = unquote(value)
                if decoded == value:
                    break
                value = decoded
            else:
                raise SnapshotError('encoding_too_deep')


def parse_rows(raw, resource):
    try:
        text = raw.decode('utf-8-sig').strip()
    except UnicodeError:
        raise SnapshotError('invalid_json') from None
    empty = re.compile(r'No items where found for model(?:(?:\s*:\s*|\s+)([A-Za-z][A-Za-z0-9_]*))?\s*')

    def is_empty_message(value):
        # The live legacy endpoint wraps the optional model in this exact tag.
        # Do not strip arbitrary HTML: unrelated pages must not end an export.
        html_marker = re.fullmatch(
            r'No items where found for model\s+<b>([A-Za-z][A-Za-z0-9_]*)?</b>', value)
        if html_marker:
            value = 'No items where found for model'
            if html_marker.group(1):
                value += ' ' + html_marker.group(1)
        match = empty.fullmatch(value)
        if not match:
            return False
        allowed_models = {resource.name.casefold()}
        if resource.name == 'contacts':
            allowed_models.add('contact')
        if match.group(1) is not None and match.group(1).casefold() not in allowed_models:
            raise SnapshotError('unexpected_structure')
        return True

    if is_empty_message(text):
        return []
    try:
        value = json.loads(text)
    except ValueError:
        raise SnapshotError('invalid_json') from None
    for _ in range(4):
        if isinstance(value, str) and is_empty_message(value):
            return []
        if isinstance(value, list) and all(isinstance(row, dict) for row in value):
            return value
        if isinstance(value, dict):
            if value.get('error') or value.get('errors'):
                break
            if 'source' in value and value['source'] != API_ORIGIN:
                raise SnapshotError('wrong_source')
            if resource.id_field and resource.id_field in value:
                return [value]
            containers = [value[name] for name in ('data', 'items', 'contacts') if name in value]
            if len(containers) == 1:
                value = containers[0]
                continue
        break
    raise SnapshotError('unexpected_structure')


def page_key(resource, page):
    return int.from_bytes(hashlib.sha256((FORMAT + ':' + resource + ':' + str(page)).encode()).digest()[:8], 'big') % (2**63 - 1) + 1


def protect_page(resource, page, raw, snapshot):
    envelope = {'format': FORMAT, 'account': ACCOUNT, 'source': API_ORIGIN,
        'resource': resource, 'page': page, 'snapshot': snapshot,
        'sha256': hashlib.sha256(raw).hexdigest(), 'body': base64.b64encode(raw).decode('ascii')}
    return _crypt(page_key(resource, page), zlib.compress(json.dumps(envelope).encode(), 6))


def unprotect_page(resource, page, encrypted):
    value = json.loads(zlib.decompress(_crypt(page_key(resource, page), encrypted, decrypt=True)))
    if (value.get('format'), value.get('account'), value.get('source'), value.get('resource'), value.get('page')) != (FORMAT, ACCOUNT, API_ORIGIN, resource, page):
        raise SnapshotError('invalid_archive')
    raw = base64.b64decode(value.pop('body'), validate=True)
    if hashlib.sha256(raw).hexdigest() != value.get('sha256'):
        raise SnapshotError('invalid_archive')
    return dict(value, raw=raw)


def private_directory(directory):
    directory = Path(directory).resolve()
    if any((parent / '.git').exists() for parent in (directory, *directory.parents)):
        raise SnapshotError('private_output_required')
    for name in ('snapshot.sqlite', 'snapshot.sqlite-journal', 'contacts.sqlite',
                 'contacts.sqlite-journal', 'contacts.tmp.sqlite', 'collector.lock',
                 'progress.json', 'progress.tmp.json', 'STOP'):
        path = directory / name
        if path.is_symlink() or (path.exists() and (not path.is_file() or path.stat().st_nlink != 1)):
            raise SnapshotError('private_output_required')
    return directory


def open_archive(path, page_size):
    db = sqlite3.connect(path)
    try:
        expected = {'format': FORMAT, 'account': ACCOUNT, 'source': API_ORIGIN, 'page_size': str(page_size)}
        tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if tables:
            if 'metadata' not in tables:
                raise SnapshotError('invalid_archive')
            actual = dict(db.execute('SELECT key,value FROM metadata'))
            if (any(actual.get(key) != value for key, value in expected.items())
                    or not re.fullmatch(r'[a-f0-9]{32}', actual.get('snapshot', ''))):
                raise SnapshotError('archive_metadata_mismatch')
        db.execute('PRAGMA synchronous=FULL')
        db.executescript('''
            CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY,value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS pages (
                version_id INTEGER PRIMARY KEY, module TEXT NOT NULL, account TEXT NOT NULL,
                source TEXT NOT NULL, resource TEXT NOT NULL,page INTEGER NOT NULL,
                sha256 TEXT NOT NULL,row_count INTEGER NOT NULL,captured_at TEXT NOT NULL,
                parse_code TEXT NOT NULL,raw_encrypted BLOB NOT NULL);
            CREATE INDEX IF NOT EXISTS accepted_page ON pages(resource,page,parse_code);
            CREATE TABLE IF NOT EXISTS row_ids (resource TEXT NOT NULL,source_id INTEGER NOT NULL,
                PRIMARY KEY(resource,source_id));
            CREATE TABLE IF NOT EXISTS resource_state (resource TEXT PRIMARY KEY,next_page INTEGER NOT NULL,
                row_count INTEGER NOT NULL,status TEXT NOT NULL,error_code TEXT);
            CREATE TABLE IF NOT EXISTS events (id INTEGER PRIMARY KEY,occurred_at TEXT NOT NULL,
                resource TEXT,page INTEGER,code TEXT NOT NULL);
        ''')
        if not tables:
            with db:
                db.executemany('INSERT INTO metadata VALUES (?,?)', dict(expected, snapshot=uuid.uuid4().hex).items())
        return db
    except BaseException:
        db.close()
        raise


def index_rows(db, ids):
    db.executemany('INSERT OR IGNORE INTO contacts VALUES (?,?)', ((ident,
        json.dumps({'source': API_ORIGIN, 'contact': {'id': ident}}, separators=(',', ':'))) for ident in ids))


def rebuild_index(folder, archive):
    temporary = folder / 'contacts.tmp.sqlite'
    temporary.unlink(missing_ok=True)
    with closing(sqlite3.connect(temporary)) as db:
        db.execute('CREATE TABLE contacts (id INTEGER PRIMARY KEY,record_json TEXT NOT NULL)')
        index_rows(db, (row[0] for row in archive.execute("SELECT source_id FROM row_ids WHERE resource='contacts' ORDER BY source_id")))
        db.commit()
    os.replace(temporary, folder / 'contacts.sqlite')


def read_link_progress(folder, snapshot):
    """Only safe fixed phase and aggregate integers may reach the GUI."""
    if not isinstance(snapshot, str) or not re.fullmatch(r'[a-f0-9]{32}', snapshot):
        return {}
    try:
        path = Path(folder) / ('links-' + snapshot) / 'progress.json'
        if path.is_symlink():
            return {}
        value = read_json(path)
        result = {'status': value['status']} if value.get('status') in LINK_STATUSES else {}
        result.update((field, value[field]) for field in
            ('verified_total', 'total_contacts', 'request_attempts', 'failed_contacts')
            if type(value.get(field)) is int and 0 <= value[field] < 2**63)
        result.update((field, value[field]) for field in
            ('current_requests_per_second', 'target_requests_per_second')
            if type(value.get(field)) in (int, float) and 0 < value[field] <= 5
            and math.isfinite(value[field]))
        return result
    except (OSError, ValueError, TypeError):
        return {}


def collect(output_directory, *, account=ACCOUNT, key=None, key_provider=None, resources=RESOURCES,
            page_size=100, requests_per_second=1.0, max_attempts=3, fetch=read_page,
            clock=time.monotonic, wait=time.sleep, stop_requested=None, collect_links=False,
            link_collector=None, on_progress=None, link_requests_per_second=1.0):
    if account != ACCOUNT:
        raise SnapshotError('wrong_account')
    if (type(page_size) is not int or not 1 <= page_size <= 100 or type(max_attempts) is not int
            or not 1 <= max_attempts <= 5 or isinstance(requests_per_second, bool)
            or not isinstance(requests_per_second, (int, float)) or not math.isfinite(requests_per_second)
            or not 0 < requests_per_second <= 1 or type(collect_links) is not bool
            or type(link_requests_per_second) not in (int, float)
            or not 0 < link_requests_per_second <= 5 or not math.isfinite(link_requests_per_second)
            or not isinstance(resources, (tuple, list)) or not resources
            or any(not isinstance(item, Resource) for item in resources)
            or len({item.name for item in resources}) != len(resources)
            or any(INVENTORY.get(item.name) != item for item in resources)):
        raise SnapshotError('invalid_arguments')
    folder = private_directory(output_directory)
    report = {'mode': 'legacy_read_only_snapshot', 'account': ACCOUNT, 'status': 'initializing',
        'request_attempts': 0, 'consecutive_errors': 0, 'error_code': None, 'resources': {},
        'gaps': GAPS, 'snapshot_consistency': 'provider_snapshot_isolation_not_verified',
        'list_personal_links': 'untrusted_not_for_login', 'key_stored': False,
        'source_values_printed': False, 'frappe_changed': False, 'links_status': 'not_requested'}
    next_request = clock()

    def check_stop():
        if (folder / 'STOP').exists() or (stop_requested and stop_requested()):
            raise SnapshotError('cancelled')

    def until(deadline):
        while True:
            check_stop()
            remaining = deadline - clock()
            if remaining <= 0:
                return
            wait(min(0.25, remaining))

    def progress(db):
        report['resources'] = {name: {'status': status, 'rows': count, 'next_page': page,
            'error_code': code, 'id_validation': 'enabled' if INVENTORY[name].id_field else 'undocumented_id'}
            for name, page, count, status, code in db.execute('SELECT * FROM resource_state')}
        write_json(folder / 'progress.json', report, temporary=folder / 'progress.tmp.json')
        if on_progress:
            on_progress(json.loads(json.dumps(report)))

    with writer_lock(folder), closing(open_archive(folder / 'snapshot.sqlite', page_size)) as db:
        snapshot = dict(db.execute('SELECT key,value FROM metadata'))['snapshot']
        report['snapshot'] = snapshot
        rebuild_index(folder, db)
        with db:
            db.executemany('INSERT OR IGNORE INTO resource_state VALUES (?,0,0,?,NULL)',
                ((item.name, 'not_started') for item in resources))
        try:
            key = parse_key(key if key is not None else key_provider() if key_provider else None)
            report['status'] = 'collecting'
            progress(db)
            for resource in resources:
                report['current_resource'] = resource.name
                progress(db)
                page, count, status = db.execute('SELECT next_page,row_count,status FROM resource_state WHERE resource=?', (resource.name,)).fetchone()
                if status == 'complete':
                    continue
                while True:
                    check_stop()
                    reply = None
                    code = None
                    for attempt in range(max_attempts):
                        until(next_request)
                        next_request = clock() + 1 / requests_per_second
                        report['request_attempts'] += 1
                        progress(db)
                        reply = None
                        try:
                            reply = fetch(key, resource.name, page, page_size,
                                resource.id_field + ' ASC' if resource.id_field else None)
                            if (not isinstance(reply, Response) or type(reply.status) is not int
                                    or not 100 <= reply.status <= 599 or not isinstance(reply.body, bytes)):
                                raise SnapshotError('unexpected_structure')
                            if len(reply.body) > MAX_BODY:
                                raise SnapshotError('response_too_large')
                            reject_key_leak(reply.body, key)
                            code = None if reply.status == 200 else 'http_' + str(reply.status)
                        except Exception as error:
                            code = safe_code(error)
                        retryable = code in {'network_error', 'http_408', 'http_429'} or bool(code and re.fullmatch(r'http_5\d\d', code))
                        delay = 0
                        if reply and reply.retry_after is not None:
                            try:
                                delay = float(reply.retry_after)
                            except (ValueError, TypeError):
                                try:
                                    delay = (parsedate_to_datetime(reply.retry_after) - datetime.now(timezone.utc)).total_seconds()
                                except (ValueError, TypeError, OverflowError):
                                    delay = 0
                            if not math.isfinite(delay) or delay > 300:
                                raise SnapshotError('retry_after_excessive')
                        next_request = max(next_request, clock() + max(0, delay))
                        if not retryable or attempt + 1 == max_attempts:
                            break
                        # Intermediate error responses are source evidence too;
                        # never replace or silently discard an earlier capture.
                        if reply is not None:
                            with db:
                                db.execute('INSERT INTO pages VALUES (NULL,?,?,?,?,?,?,?,?,?,?)', (FORMAT,
                                    ACCOUNT, API_ORIGIN, resource.name, page, hashlib.sha256(reply.body).hexdigest(),
                                    0, utc_now(), code, protect_page(resource.name, page, reply.body, snapshot)))
                        with db:
                            db.execute('INSERT INTO events VALUES (NULL,?,?,?,?)', (utc_now(), resource.name, page, code))
                        progress(db)
                        next_request = max(next_request, clock() + min(30, 2**attempt))
                    # Even final failed attempts must honor provider backoff before
                    # another resource, optional link worker, or the next invocation.
                    until(next_request if code else clock())
                    ids, records = [], None
                    if code is None:
                        try:
                            records = parse_rows(reply.body, resource)
                            if len(records) > page_size:
                                raise SnapshotError('page_too_large')
                            if resource.id_field:
                                for row in records:
                                    ident = row.get(resource.id_field)
                                    if type(ident) is str and re.fullmatch(r'[1-9][0-9]{0,18}', ident):
                                        ident = int(ident)
                                    if type(ident) is not int or not 0 < ident < 2**63:
                                        raise SnapshotError('invalid_id')
                                    ids.append(ident)
                                if len(set(ids)) != len(ids):
                                    raise SnapshotError('duplicate_ids')
                            digest = hashlib.sha256(reply.body).hexdigest()
                            if records and db.execute("SELECT 1 FROM pages WHERE resource=? AND sha256=? AND parse_code='accepted' LIMIT 1", (resource.name, digest)).fetchone():
                                raise SnapshotError('repeated_page')
                            if any(db.execute('SELECT 1 FROM row_ids WHERE resource=? AND source_id=?', (resource.name, ident)).fetchone() for ident in ids):
                                raise SnapshotError('duplicate_ids')
                        except Exception as error:
                            code = safe_code(error)
                    immediate = code in {'http_401', 'api_key_in_response', 'wrong_source',
                        'redirect_blocked', 'encoding_too_deep', 'unverifiable_encoding'}
                    if code:
                        status = ('partial' if count else 'access_denied' if code == 'http_403'
                                  else 'unavailable' if code == 'http_404' else 'error')
                    else:
                        status = 'collecting' if records else 'complete' if count else 'empty_inferred'
                    if reply is not None and code not in {'api_key_in_response', 'encoding_too_deep',
                                                         'wrong_source', 'unverifiable_encoding'}:
                        encrypted = protect_page(resource.name, page, reply.body, snapshot)
                    else:
                        encrypted = None
                    with db:
                        if encrypted is not None:
                            db.execute('INSERT INTO pages VALUES (NULL,?,?,?,?,?,?,?,?,?,?)', (FORMAT,
                                ACCOUNT, API_ORIGIN, resource.name, page, hashlib.sha256(reply.body).hexdigest(),
                                len(records) if records is not None else 0, utc_now(), code or ('accepted' if records else status), encrypted))
                        if not code and records:
                            db.executemany('INSERT INTO row_ids VALUES (?,?)', ((resource.name, ident) for ident in ids))
                            page, count = page + 1, count + len(records)
                        db.execute('UPDATE resource_state SET next_page=?,row_count=?,status=?,error_code=? WHERE resource=?',
                            (page, count, status, code, resource.name))
                        db.execute('INSERT INTO events VALUES (NULL,?,?,?,?)', (utc_now(), resource.name, page, code or status))
                    if not code and ids and resource.name == 'contacts':
                        with closing(sqlite3.connect(folder / 'contacts.sqlite')) as index:
                            with index:
                                index_rows(index, ids)
                    reply, records = None, None
                    report['consecutive_errors'] = report['consecutive_errors'] + 1 if code and code not in {'http_403', 'http_404'} else 0
                    progress(db)
                    if immediate:
                        raise SnapshotError(code)
                    if report['consecutive_errors'] >= FAILURE_LIMIT:
                        raise SnapshotError('failure_limit')
                    if code or status != 'collecting':
                        break
            errors = any(item['status'] in {'partial', 'error'} for item in report['resources'].values())
            report.update(status='completed_with_errors' if errors else 'completed_with_gaps',
                          error_code='resource_errors' if errors else None)
            if collect_links:
                state = report['resources'].get('contacts', {})
                if state.get('status') != 'complete' or not state.get('rows'):
                    report['links_status'] = 'source_contacts_incomplete'
                    report.update(status='stopped', error_code='link_collection_failed')
                else:
                    check_stop()
                    report['status'] = 'collecting_links'
                    report['current_resource'] = 'contacts'
                    progress(db)
                    if link_collector is None:
                        from collect_personal_links_bulk import collect as link_collector
                    result = link_collector(folder / 'contacts.sqlite', folder / ('links-' + snapshot),
                        account=ACCOUNT, key=key, requests_per_second=link_requests_per_second,
                        stop_requested=lambda: (folder / 'STOP').exists() or bool(stop_requested and stop_requested()))
                    link_status = result.get('status') if isinstance(result, dict) else None
                    report['links_status'] = link_status if link_status in LINK_STATUSES else 'incomplete'
                    if link_status != 'completed':
                        report.update(status='cancelled' if link_status == 'cancelled' else 'stopped',
                                      error_code='link_collection_failed')
                    else:
                        report.update(status='completed_with_errors' if errors else 'completed_with_gaps',
                                      error_code='resource_errors' if errors else None)
        except KeyboardInterrupt:
            report.update(status='cancelled', error_code='cancelled')
        except Exception as error:
            code = safe_code(error)
            report.update(status='cancelled' if code == 'cancelled' else 'stopped', error_code=code)
        finally:
            key = None
            progress(db)
    return report


def graphical_collect(directory, collect_links=False):
    import tkinter as tk
    from tkinter import messagebox, ttk
    root = tk.Tk()
    root.withdraw()
    root.title(PROFILE.label + ' — архив доступных данных АВО (только чтение)')
    frame = ttk.Frame(root, padding=20)
    frame.grid()
    ttk.Label(frame, text='Полный обход документированных ресурсов API ' + PROFILE.label, font=('', 12)).grid(sticky='w')
    ttk.Label(frame, text='Назначение запросов: ' + API_ORIGIN + '\n'
        'Контакты (включая пароли), сотрудники, курсы, доступы, счета и другие доступные ресурсы.\n'
        'Ответы сохраняются зашифрованными для текущего пользователя Windows.\n'
        'Только чтение АВО. Во Frappe изменений не будет. Полнота всех разделов не обещается.\n'
        'После сбоя повторный запуск продолжает тот же снимок. Новый снимок — новая папка.').grid(sticky='w', pady=10)
    if collect_links:
        ttk.Label(frame, text='После основных разделов программа отдельно соберёт персональные ссылки.\n'
                  'Предел — 3 запроса/сек, с автоматическим снижением при ограничении API.').grid(sticky='w', pady=6)
    ttk.Label(frame, text='API KEY GET ' + PROFILE.label + ' — только в памяти этого процесса:').grid(sticky='w')
    entry = ttk.Entry(frame, width=72, show='*')
    entry.grid(sticky='ew')
    label = ttk.Label(frame, text='Готов к запуску.')
    label.grid(sticky='w', pady=12)
    messages, stopped, result = queue.Queue(), threading.Event(), []
    active = False
    current = {}
    last_link_poll = 0.0

    def start():
        nonlocal active
        try:
            secret = parse_key(entry.get())
        except Exception:
            messagebox.showerror('Проверьте ключ', 'Нужен API KEY GET аккаунта ' + PROFILE.label + '.', parent=root)
            return
        entry.delete(0, 'end')
        entry.configure(state='disabled')
        start_button.configure(state='disabled')
        active = True
        def worker():
            nonlocal secret
            try:
                value = collect(directory, key=secret, collect_links=collect_links,
                    stop_requested=stopped.is_set, on_progress=lambda report: messages.put(('progress', report)),
                    link_requests_per_second=3.0)
            except Exception as error:
                value = {'status': 'stopped', 'error_code': safe_code(error)}
            finally:
                secret = None
            messages.put(('done', value))
        threading.Thread(target=worker, daemon=False).start()

    def poll():
        nonlocal active, last_link_poll
        try:
            while True:
                kind, value = messages.get_nowait()
                current.update(value)
                label.configure(text=value['status'] + ' | ' + value.get('current_resource', '')
                    + ' | Запросов: ' + str(value.get('request_attempts', 0)))
                if kind == 'done':
                    result.append(value)
                    active = False
                    text = 'Сбор завершён. Подробности по ресурсам сохранены в progress.json.' if value['status'] == 'completed_with_gaps' else 'Требуется проверка: ' + str(value.get('error_code') or 'internal_failure')
                    messagebox.showinfo(PROFILE.label + ' — результат', text, parent=root)
        except queue.Empty:
            pass
        if active and current.get('status') == 'collecting_links' and time.monotonic() - last_link_poll >= 1:
            last_link_poll = time.monotonic()
            counts = read_link_progress(directory, current.get('snapshot'))
            if counts:
                label.configure(text='Персональные ссылки: ' + str(counts.get('verified_total', 0))
                    + ' / ' + str(counts.get('total_contacts', 0))
                    + ' | Запросов: ' + str(counts.get('request_attempts', 0))
                    + (' | Предел: ' + str(counts['current_requests_per_second']) + '/с'
                       if 'current_requests_per_second' in counts else ''))
        root.after(150, poll)

    def close():
        if active:
            stopped.set()
            label.configure(text='Останавливаю и сохраняю результат…')
        else:
            root.destroy()
    start_button = ttk.Button(frame, text='Начать / продолжить архивирование', command=start)
    start_button.grid(sticky='e')
    ttk.Button(frame, text='Остановить', command=stopped.set).grid(sticky='e', pady=8)
    root.protocol('WM_DELETE_WINDOW', close)
    root.update_idletasks()
    root.geometry('+' + str(max(0, (root.winfo_screenwidth() - root.winfo_reqwidth()) // 2))
                  + '+' + str(max(0, (root.winfo_screenheight() - root.winfo_reqheight()) // 2)))
    root.attributes('-topmost', True)
    root.deiconify()
    root.lift()
    entry.focus_force()
    root.after(1500, lambda: root.attributes('-topmost', False))
    root.after(150, poll)
    root.mainloop()
    return result[-1] if result else {'status': 'cancelled', 'error_code': 'cancelled'}


class SafeParser(argparse.ArgumentParser):
    def error(self, message):
        raise SnapshotError('invalid_arguments')


def main(argv=None):
    try:
        parser = SafeParser(description=__doc__)
        parser.add_argument('--output-directory', required=True, type=Path)
        parser.add_argument('--collect-links', action='store_true')
        args = parser.parse_args(argv)
        private_directory(args.output_directory)
        report = graphical_collect(args.output_directory, args.collect_links)
    except Exception as error:
        report = {'status': 'not_started', 'error_code': safe_code(error)}
    print(json.dumps(report, ensure_ascii=True, sort_keys=True))
    return 0 if report['status'] == 'completed_with_gaps' else 1


if __name__ == '__main__':
    raise SystemExit(main())

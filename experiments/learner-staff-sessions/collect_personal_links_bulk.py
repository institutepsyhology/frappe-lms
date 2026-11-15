"""Resumable, read-only individual-card collection of ALL MV-Centr login links.

Run locally under the Windows user who owns the DPAPI archive. No key argument,
environment variable, browser login, link redemption, or Frappe write is used.
The masked key window appears once; the key lives only in this process's memory.
Place STOP in the private output directory to cancel between/between-retry waits.
"""
from __future__ import annotations

import argparse
from array import array
from bisect import bisect_left
from contextlib import closing, contextmanager
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import hashlib
import json
import math
import os
from pathlib import Path
import re
import sqlite3
import time
from urllib.parse import unquote

from audit_legacy_links import API_ORIGIN
from collect_personal_links import (
    CollectionError, ERROR_CODES, normalize_detail, parse_key, read_detail, verified_link,
)
from private_link_storage import StorageError, protect_url, unprotect_url
from progress_io import ProgressWriteError, read_json, write_json


ACCOUNT = 'mv-centr'
REPOSITORY = Path(__file__).resolve().parents[2]
MAX_ATTEMPTS = 3
FAILURE_LIMIT = 10
MAX_REQUESTS_PER_SECOND = 5.0
RECOVERY_SUCCESSES = 100
RETRYABLE = frozenset({'network_error', 'http_408', 'http_429'})
BULK_CODES = frozenset({
    'invalid_arguments', 'wrong_account', 'wrong_source_archive', 'empty_source_archive',
    'private_output_required', 'source_output_overlap', 'collector_already_running',
    'archive_metadata_mismatch', 'invalid_private_archive', 'invalid_seed_archive',
    'token_collision', 'retry_after_excessive', 'internal_failure', 'cancelled',
    'invalid_key_input', 'private_storage_failed', 'progress_file_locked',
})
# Missing links and a deleted contact may be isolated source conditions. Other
# malformed replies are evidence of an API/schema/account problem: stop at once.
CONTACT_FAILURES = frozenset({'detail_missing_link', 'http_400', 'http_404'})


class BulkError(CollectionError):
    pass


class Cancelled(BulkError):
    def __init__(self):
        super().__init__('cancelled')


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec='microseconds')


def safe_code(error):
    """Never format an exception: urllib/SQLite exceptions may contain secrets."""
    if isinstance(error, ProgressWriteError):
        return 'progress_file_locked'
    if isinstance(error, (CollectionError, StorageError)) and len(error.args) == 1:
        code = error.args[0]
        if isinstance(code, str) and (code in ERROR_CODES or code in BULK_CODES
                or re.fullmatch(r'http_[1-5][0-9]{2}', code)):
            return code
    return 'internal_failure'


def is_retryable(code):
    return code in RETRYABLE or bool(re.fullmatch(r'http_5[0-9]{2}', code))


def immediate_stop(code):
    return not (is_retryable(code) or code in CONTACT_FAILURES)


class AdaptiveRate:
    """Local speed setting plus provider backoff; contains no account secrets."""
    def __init__(self, directory, target):
        self.path = Path(directory) / 'speed.json'
        self.default = self.target = float(target)
        self.ceiling = MAX_REQUESTS_PER_SECOND
        self.clean = 0
        self.warning = None

    @property
    def current(self):
        return min(self.target, self.ceiling)

    def refresh(self):
        try:
            if self.path.is_symlink():
                self.warning = 'invalid_speed_setting'
                return
            try:
                self.path.stat()
            except FileNotFoundError:
                value = self.default
            else:
                # Windows can retain the same timestamp for a rapid same-size
                # replacement. Read the bounded control instead of caching stat.
                settings = read_json(self.path, max_bytes=256)
                if set(settings) != {'requests_per_second'}:
                    raise ValueError('invalid_speed_setting')
                value = settings['requests_per_second']
            if type(value) not in (int, float) or not 0 < value <= MAX_REQUESTS_PER_SECOND or not math.isfinite(value):
                raise ValueError('invalid_speed_setting')
            self.target = float(value)
            # Manual changes cannot undo the separate adaptive throttle ceiling.
            self.warning = None
        except (OSError, ValueError, TypeError):
            self.warning = 'invalid_speed_setting'

    def failed(self):
        self.ceiling = max(0.25, self.current / 2)
        self.clean = 0

    def succeeded(self):
        self.clean += 1
        if self.clean >= RECOVERY_SUCCESSES:
            self.ceiling = min(MAX_REQUESTS_PER_SECOND, self.ceiling + 0.25)
            self.clean = 0


def validate_source(database, account):
    """Validate EVERY source ID/account before any network request or key prompt.

    Keep only sorted numeric IDs (about 1.7 MiB for 214k contacts), never profiles.
    Links from the defective list response are deliberately not trusted here.
    """
    if account != ACCOUNT:
        raise BulkError('wrong_account')
    path = Path(database).resolve()
    ids = array('q')
    digest = hashlib.sha256(API_ORIGIN.encode('ascii'))
    try:
        with closing(sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)) as source:
            source.execute('PRAGMA query_only=ON')
            for ident, raw in source.execute('SELECT id, record_json FROM contacts ORDER BY id'):
                if type(ident) is not int or not 0 < ident < 2**63:
                    raise BulkError('wrong_source_archive')
                record = json.loads(raw)
                contact = record.get('contact') if isinstance(record, dict) else None
                if (not isinstance(record, dict) or record.get('source') != API_ORIGIN
                        or not isinstance(contact, dict) or str(contact.get('id')) != str(ident)
                        or (ids and ident <= ids[-1])):
                    raise BulkError('wrong_source_archive')
                ids.append(ident)
                digest.update(str(ident).encode('ascii') + b'\n')
    except (sqlite3.Error, ValueError, TypeError, UnicodeError, OSError):
        raise BulkError('wrong_source_archive') from None
    if not ids:
        raise BulkError('empty_source_archive')
    return ids, digest.hexdigest()


def private_output(directory, source_database, seed_database=None):
    directory = Path(directory).resolve()
    if directory == REPOSITORY or REPOSITORY in directory.parents:
        raise BulkError('private_output_required')
    protected_paths = [Path(source_database).resolve()]
    if seed_database is not None:
        protected_paths.append(Path(seed_database).resolve())
    # Refuse symlink/hardlink aliases too: a misplaced output file must never
    # make SQLite or the atomic-progress temporary file modify the source.
    for name in ('links.sqlite', 'links.sqlite-wal', 'links.sqlite-shm',
                 'collector.lock', 'progress.json', 'progress.json.tmp', 'speed.json', 'speed.json.tmp'):
        candidate = directory / name
        if candidate.is_symlink():
            raise BulkError('private_output_required')
        for protected in protected_paths:
            if candidate.resolve() == protected or (candidate.exists() and protected.exists()
                    and os.path.samefile(candidate, protected)):
                raise BulkError('source_output_overlap')
    return directory


@contextmanager
def writer_lock(directory):
    """OS-held lock releases on crash; retain the inert lock file to avoid races."""
    directory.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(directory / 'collector.lock', os.O_RDWR | os.O_CREAT, 0o600)
    locked = False
    try:
        if os.fstat(descriptor).st_size == 0:
            os.write(descriptor, b'0')
        os.lseek(descriptor, 0, os.SEEK_SET)
        try:
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(descriptor, msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            locked = True
        except OSError:
            raise BulkError('collector_already_running') from None
        yield
    finally:
        if locked:
            os.lseek(descriptor, 0, os.SEEK_SET)
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(descriptor, msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)


def open_output(path, source_fingerprint, total):
    descriptor = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
    os.close(descriptor)
    db = sqlite3.connect(path)
    try:
        expected = {'schema': 'mvcentr-individual-links-v1', 'account': ACCOUNT,
                    'origin': API_ORIGIN, 'source_ids_sha256': source_fingerprint,
                    'source_count': str(total)}
        tables = {row[0] for row in db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}
        # Inspect before any DDL/journal change. The small preflight archive is
        # a read-only seed, never an in-place conversion or resume destination.
        if tables:
            if 'metadata' not in tables:
                raise BulkError('invalid_private_archive')
            if dict(db.execute('SELECT key,value FROM metadata')) != expected:
                raise BulkError('archive_metadata_mismatch')
        db.execute('PRAGMA foreign_keys=ON')
        db.execute('PRAGMA journal_mode=WAL')
        db.execute('PRAGMA synchronous=FULL')
        db.execute('PRAGMA busy_timeout=5000')
        db.executescript('''
            BEGIN IMMEDIATE;
            CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS links (
                version_id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_id INTEGER NOT NULL CHECK(source_id > 0),
                url_encrypted BLOB NOT NULL,
                token_digest BLOB NOT NULL,
                captured_at TEXT NOT NULL,
                source_field TEXT NOT NULL CHECK(source_field = 'link_personal_auth'),
                capture_origin TEXT NOT NULL CHECK(capture_origin IN ('individual_detail','seed_preflight'))
            );
            CREATE INDEX IF NOT EXISTS links_source ON links(source_id, version_id);
            CREATE INDEX IF NOT EXISTS links_digest ON links(token_digest);
            CREATE TABLE IF NOT EXISTS contact_state (
                source_id INTEGER PRIMARY KEY,
                latest_version INTEGER NOT NULL REFERENCES links(version_id),
                verified_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS events (
                event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                occurred_at TEXT NOT NULL, source_id INTEGER, code TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS diagnostics (
                id INTEGER PRIMARY KEY, occurred_at TEXT NOT NULL,
                stage TEXT NOT NULL, error_type TEXT NOT NULL,
                errno INTEGER, winerror INTEGER
            );
        ''')
        actual = dict(db.execute('SELECT key, value FROM metadata'))
        if actual and actual != expected:
            raise BulkError('archive_metadata_mismatch')
        if not actual:
            with db:
                db.executemany('INSERT INTO metadata VALUES (?, ?)', expected.items())
        invalid = db.execute('''SELECT 1 FROM contact_state s LEFT JOIN links l
            ON l.version_id=s.latest_version WHERE l.version_id IS NULL
            OR l.source_id<>s.source_id LIMIT 1''').fetchone()
        if invalid:
            raise BulkError('invalid_private_archive')
        validate_remote_receipts(db)
        db.commit()
        return db
    except BaseException:
        db.close()
        raise


def validate_remote_receipts(db):
    """An evicted ciphertext must retain a matching durable delivery receipt."""
    prefix = b'REMOTE:MVC-FRAPPE:v1:'
    if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='delivery_receipts'").fetchone():
        if not db.execute('SELECT 1 FROM links WHERE substr(url_encrypted,1,?)=? LIMIT 1',
                          (len(prefix),prefix)).fetchone(): return
        raise BulkError('invalid_private_archive')
    invalid=db.execute('''SELECT 1 FROM delivery_receipts r LEFT JOIN links l ON r.version_id=l.version_id
        WHERE l.version_id IS NULL OR length(r.snapshot)<>32 OR r.snapshot GLOB '*[^a-f0-9]*'
        OR length(r.sha256)<>64 OR r.sha256 GLOB '*[^a-f0-9]*' OR r.target<>'my-lk.mv-centr.ru'
        OR l.url_encrypted<>CAST(? || r.snapshot || ':' || l.version_id || ':' || r.sha256 AS BLOB) LIMIT 1''',
        (prefix.decode('ascii'),)).fetchone()
    if invalid: raise BulkError('invalid_private_archive')
    invalid=db.execute('''SELECT 1 FROM links l LEFT JOIN delivery_receipts r ON r.version_id=l.version_id
        WHERE substr(l.url_encrypted,1,?)=? AND (r.version_id IS NULL
        OR length(r.snapshot)<>32 OR r.snapshot GLOB '*[^a-f0-9]*'
        OR length(r.sha256)<>64 OR r.sha256 GLOB '*[^a-f0-9]*'
        OR r.target<>'my-lk.mv-centr.ru'
        OR l.url_encrypted<>CAST(? || r.snapshot || ':' || l.version_id || ':' || r.sha256 AS BLOB)) LIMIT 1''',
        (len(prefix),prefix,prefix.decode('ascii'))).fetchone()
    if invalid: raise BulkError('invalid_private_archive')


def record_event(db, source_id, code):
    # Only callers' fixed codes reach this table. No HTTP URLs/exception messages.
    if code not in {'verified', 'seed_verified', 'retry', 'stopped', 'cancelled'} and not (
            code in ERROR_CODES or code in BULK_CODES or re.fullmatch(r'http_[1-5][0-9]{2}', code)):
        code = 'internal_failure'
    db.execute('INSERT INTO events (occurred_at, source_id, code) VALUES (?, ?, ?)',
               (utc_now(), source_id, code))


def append_verified(db, ident, encrypted, digest, captured_at, origin):
    """Version + success cursor + audit event commit together, never on failures."""
    if db.execute('SELECT 1 FROM links WHERE token_digest=? AND source_id<>? LIMIT 1',
                  (digest, ident)).fetchone():
        raise BulkError('token_collision')
    with db:
        cursor = db.execute('''INSERT INTO links
            (source_id,url_encrypted,token_digest,captured_at,source_field,capture_origin)
            VALUES (?,?,?,?,?,?)''', (ident, encrypted, digest, captured_at, 'link_personal_auth', origin))
        db.execute('''INSERT INTO contact_state VALUES (?,?,?) ON CONFLICT(source_id)
            DO UPDATE SET latest_version=excluded.latest_version, verified_at=excluded.verified_at''',
                   (ident, cursor.lastrowid, utc_now()))
        record_event(db, ident, 'seed_verified' if origin == 'seed_preflight' else 'verified')


def reject_key_leak(url, key):
    key_forms = {key}
    decoded_key = key
    for _ in range(16):
        decoded = unquote(decoded_key, errors='strict')
        key_forms.add(decoded)
        if decoded == decoded_key:
            break
        decoded_key = decoded
    else:
        raise BulkError('link_encoding_too_deep')
    current = url
    for _ in range(16):
        if any(value and value in current for value in key_forms):
            raise BulkError('api_key_in_link')
        decoded = unquote(current, errors='strict')
        if decoded == current:
            return
        current = decoded
    raise BulkError('link_encoding_too_deep')


def validate_link(ident, detail, key):
    detail = normalize_detail(detail, ident)
    url, digest = verified_link(ident, detail)
    reject_key_leak(url, key)
    return url, digest


def has_success(db, ident):
    return bool(db.execute('SELECT 1 FROM contact_state WHERE source_id=?', (ident,)).fetchone())


def seed_archive(db, seed_database, ids, key, check_stop):
    count = 0
    try:
        with closing(sqlite3.connect(Path(seed_database).resolve().as_uri() + '?mode=ro', uri=True)) as seed:
            seed.execute('PRAGMA query_only=ON')
            tables = {row[0] for row in seed.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}
            columns = {row[1] for row in seed.execute('PRAGMA table_info(links)')}
            if (tables != {'links'} or columns != {'source_id', 'url_encrypted', 'token_digest',
                    'captured_at', 'source_field'} or not 1 <= seed.execute(
                    'SELECT COUNT(*) FROM links').fetchone()[0] <= 3):
                raise BulkError('invalid_seed_archive')
            for ident, encrypted, previous_digest, captured, field in seed.execute(
                    'SELECT source_id,url_encrypted,token_digest,captured_at,source_field FROM links '
                    'ORDER BY source_id,captured_at'):
                check_stop()
                position = bisect_left(ids, ident) if type(ident) is int else len(ids)
                if (position == len(ids) or ids[position] != ident or field != 'link_personal_auth'
                        or not isinstance(encrypted, bytes) or not isinstance(previous_digest, bytes)
                        or not isinstance(captured, str)):
                    raise BulkError('invalid_seed_archive')
                stamp = datetime.fromisoformat(captured)
                if stamp.tzinfo is None or stamp.utcoffset() is None:
                    raise BulkError('invalid_seed_archive')
                # Decrypt and validate even a skipped duplicate: no unverified seed material.
                url = unprotect_url(ident, encrypted)
                url, digest = validate_link(ident, {'id_contact': ident, 'link_personal_auth': url}, key)
                if digest != previous_digest:
                    raise BulkError('invalid_seed_archive')
                if not has_success(db, ident):
                    append_verified(db, ident, protect_url(ident, url), digest, captured, 'seed_preflight')
                    count += 1
                url = None
    except (sqlite3.Error, ValueError, UnicodeError, TypeError, OSError):
        raise BulkError('invalid_seed_archive') from None
    return count


def retry_after(error):
    """The existing helper suppresses HTTP text but retains HTTPError context/headers."""
    value = getattr(error, 'retry_after', None)
    context = error
    for _ in range(4):
        headers = getattr(context, 'headers', None)
        if value is None and headers is not None:
            value = headers.get('Retry-After')
        context = getattr(context, '__context__', None)
        if context is None:
            break
    if value is None:
        return 0.0
    try:
        delay = float(value)
    except (TypeError, ValueError, OverflowError):
        try:
            stamp = parsedate_to_datetime(value)
            if stamp.tzinfo is None:
                stamp = stamp.replace(tzinfo=timezone.utc)
            delay = (stamp - datetime.now(timezone.utc)).total_seconds()
        except (TypeError, ValueError, OverflowError):
            return 0.0
    if not math.isfinite(delay) or delay > 86400:
        raise BulkError('retry_after_excessive')
    return max(delay, 0.0)


def atomic_progress(directory, report):
    write_json(directory / 'progress.json', dict(report, updated_at=utc_now()))


def record_diagnostic(db, stage, error):
    """Record exception category/numeric OS codes, never messages or tracebacks."""
    numeric = lambda value: value if type(value) is int else None
    with db:
        db.execute('INSERT INTO diagnostics (occurred_at,stage,error_type,errno,winerror) VALUES (?,?,?,?,?)',
                   (utc_now(), stage, type(error).__name__, numeric(getattr(error, 'errno', None)),
                    numeric(getattr(error, 'winerror', None))))


def graphical_key(total, pending):
    import tkinter as tk
    from tkinter import messagebox, ttk
    root = tk.Tk()
    root.withdraw()
    root.title('МВЦ — полный сбор персональных ссылок')
    root.resizable(False, False)
    frame = ttk.Frame(root, padding=20)
    frame.grid()
    ttk.Label(frame, text='Полный сбор: ВСЕ контакты МВЦ', font=('', 12)).grid(sticky='w')
    ttk.Label(frame, text=f'В исходнике: {total:,}. Осталось проверить: {pending:,}.\n'
              'Каждая карточка читается отдельно; скорость подстраивается под ограничения API.\n'
              'Это длительный сбор, а не проверка трёх карточек.\n'
              'АВО используется ТОЛЬКО ДЛЯ ЧТЕНИЯ. Во Frappe изменений не будет.\n'
              'Ссылки не открываются; пароли и профили не сохраняются.').grid(sticky='w', pady=10)
    ttk.Label(frame, text='API KEY GET аккаунта МВЦ (ключ останется только в памяти):').grid(sticky='w')
    entry = ttk.Entry(frame, width=68, show='*')
    entry.grid(sticky='ew', pady=6)
    result = []

    def submit():
        try:
            key = parse_key(entry.get())
        except Exception:
            messagebox.showerror('Проверьте ключ', 'Нужен API KEY GET именно аккаунта МВЦ.', parent=root)
            return
        result.append(key)
        entry.delete(0, 'end')
        root.destroy()

    ttk.Label(frame, text='Для остановки создайте файл STOP в папке результата.\n'
              'После остановки или сбоя следующий запуск продолжит сбор.').grid(sticky='w', pady=6)
    ttk.Button(frame, text='Начать полный сбор', command=submit).grid(sticky='e', pady=10)
    root.bind('<Return>', lambda event: submit())
    root.protocol('WM_DELETE_WINDOW', root.destroy)
    root.update_idletasks()
    root.geometry('+' + str(max(0, (root.winfo_screenwidth()-root.winfo_reqwidth())//2))
                  + '+' + str(max(0, (root.winfo_screenheight()-root.winfo_reqheight())//2)))
    root.attributes('-topmost', True)
    root.deiconify()
    entry.focus_force()
    root.after(1500, lambda: root.attributes('-topmost', False))
    root.mainloop()
    if not result:
        raise Cancelled()
    return result.pop()


def collect(source_database, output_directory, *, account, key=None, key_provider=graphical_key,
            seed_database=None, refresh=False, requests_per_second=1.0, max_attempts=MAX_ATTEMPTS,
            fetch=read_detail, clock=time.monotonic, wait=time.sleep, stop_requested=None):
    """Collect all validated IDs. Injectable fetch/clock are for offline tests only."""
    if (isinstance(requests_per_second, bool) or not isinstance(requests_per_second, (int, float))
            or not 0 < requests_per_second <= MAX_REQUESTS_PER_SECOND or not math.isfinite(requests_per_second)
            or type(max_attempts) is not int or not 1 <= max_attempts <= 5 or type(refresh) is not bool):
        raise BulkError('invalid_arguments')
    folder = private_output(output_directory, source_database, seed_database)
    ids, source_fingerprint = validate_source(source_database, account)
    report = {'mode': 'all_individual_cards', 'account': ACCOUNT, 'total_contacts': len(ids),
              'requested_contacts': 0, 'request_attempts': 0, 'verified_this_run': 0, 'seeded': 0,
              'failed_contacts': 0, 'consecutive_failures': 0, 'skipped': 0,
              'verified_total': 0, 'status': 'initializing', 'error_code': None,
              'source_values_printed': False, 'frappe_changed': False,
              'links_redeemed': False, 'key_stored': False}
    stopped_path = folder / 'STOP'
    rate = AdaptiveRate(folder, requests_per_second)

    def check_stop():
        if stopped_path.exists() or (stop_requested is not None and stop_requested()):
            raise Cancelled()

    def until(deadline):
        while True:
            check_stop()
            remaining = deadline - clock()
            if remaining <= 0:
                return
            wait(min(0.25, remaining))

    with writer_lock(folder), closing(open_output(folder / 'links.sqlite', source_fingerprint, len(ids))) as db:
        def progress():
            report['verified_total'] = db.execute('SELECT COUNT(*) FROM contact_state').fetchone()[0]
            report['target_requests_per_second'] = rate.target
            report['current_requests_per_second'] = rate.current
            report['speed_setting_warning'] = rate.warning
            try:
                atomic_progress(folder, report)
            except Exception as error:
                record_diagnostic(db, 'write_progress', error)
                raise

        try:
            for ident, in db.execute('SELECT source_id FROM contact_state'):
                position = bisect_left(ids, ident) if type(ident) is int else len(ids)
                if position == len(ids) or ids[position] != ident:
                    raise BulkError('invalid_private_archive')
            progress()
            check_stop()
            pending = len(ids) if refresh else len(ids) - report['verified_total']
            if pending or seed_database is not None:
                key = parse_key(key if key is not None else key_provider(len(ids), pending))
                if seed_database is not None:
                    report['seeded'] = seed_archive(db, seed_database, ids, key, check_stop)
            report['status'] = 'collecting'
            progress()
            not_before = clock()
            last_request_at = None
            for ident in ids:
                check_stop()
                if not refresh and has_success(db, ident):
                    report['skipped'] += 1
                    continue
                report['requested_contacts'] += 1
                code = None
                for attempt in range(max_attempts):
                    while True:
                        check_stop()
                        rate.refresh()
                        deadline = max(not_before, last_request_at + 1 / rate.current
                                       if last_request_at is not None else clock())
                        remaining = deadline - clock()
                        if remaining <= 0:
                            break
                        wait(min(0.25, remaining))
                    last_request_at = clock()
                    report['request_attempts'] += 1
                    try:
                        detail = fetch(key, ident)
                        url, digest = validate_link(ident, detail, key)
                        detail = None
                        encrypted = protect_url(ident, url)
                        url = None
                        append_verified(db, ident, encrypted, digest, utc_now(), 'individual_detail')
                        code = None
                        break
                    except Exception as error:
                        record_diagnostic(db, 'read_or_store_contact', error)
                        code = safe_code(error)
                        with db:
                            record_event(db, ident, code)
                        if is_retryable(code):
                            rate.failed()
                            try:
                                server_delay = retry_after(error)
                            except BulkError as delay_error:
                                code = safe_code(delay_error)
                                with db:
                                    record_event(db, ident, code)
                                break
                            # The provider's pause applies to the next request,
                            # including the next contact after exhausted retries.
                            not_before = max(not_before, clock() + server_delay)
                        if is_retryable(code) and attempt + 1 < max_attempts:
                            delay = max(float(2**attempt), server_delay)
                            report['status'] = 'retry_wait'
                            report['error_code'] = code
                            progress()
                            not_before = max(not_before, clock() + delay)
                            until(not_before)
                            report['status'] = 'collecting'
                            continue
                        break
                    finally:
                        detail = None
                        url = None
                if code is None:
                    rate.succeeded()
                    report['verified_this_run'] += 1
                    report['consecutive_failures'] = 0
                    report['error_code'] = None
                else:
                    report['failed_contacts'] += 1
                    report['consecutive_failures'] += 1
                    report['error_code'] = code
                    if immediate_stop(code):
                        report['status'] = 'stopped_fatal_error'
                    elif report['consecutive_failures'] >= FAILURE_LIMIT:
                        report['status'] = 'stopped_consecutive_failures'
                progress()
                if report['status'].startswith('stopped_'):
                    break
            else:
                report['status'] = 'completed_with_failures' if report['failed_contacts'] else 'completed'
        except (KeyboardInterrupt, Cancelled):
            report['status'] = 'cancelled'
            report['error_code'] = 'cancelled'
            with db:
                record_event(db, None, 'cancelled')
        except Exception as error:
            record_diagnostic(db, 'collection_control', error)
            report['status'] = 'stopped_fatal_error'
            report['error_code'] = safe_code(error)
            with db:
                record_event(db, None, report['error_code'])
        finally:
            key = None
            progress()
    return report


class SafeArgumentParser(argparse.ArgumentParser):
    def error(self, message):
        raise BulkError('invalid_arguments')


def main(argv=None):
    try:
        parser = SafeArgumentParser(description=__doc__)
        parser.add_argument('--account', required=True, choices=[ACCOUNT])
        parser.add_argument('--source-database', required=True, type=Path)
        parser.add_argument('--output-directory', required=True, type=Path)
        parser.add_argument('--seed-database', type=Path)
        parser.add_argument('--refresh', action='store_true', help='Append a new verified capture for every contact.')
        parser.add_argument('--requests-per-second', type=float, default=1.0)
        parser.add_argument('--max-attempts', type=int, default=MAX_ATTEMPTS)
        args = parser.parse_args(argv)
        report = collect(args.source_database, args.output_directory, account=args.account,
                         seed_database=args.seed_database, refresh=args.refresh,
                         requests_per_second=args.requests_per_second, max_attempts=args.max_attempts)
    except KeyboardInterrupt:
        report = {'status': 'cancelled', 'error_code': 'cancelled'}
    except Exception as error:
        report = {'status': 'not_started', 'error_code': safe_code(error), 'source_values_printed': False}
    print(json.dumps(report, ensure_ascii=True, sort_keys=True))
    return 0 if report['status'] == 'completed' else 2 if report['status'] == 'cancelled' else 1


if __name__ == '__main__':
    raise SystemExit(main())

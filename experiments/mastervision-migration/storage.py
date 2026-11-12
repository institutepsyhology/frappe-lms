"""Private, compressed, account-bound source archive and resumable job ledger."""
from contextlib import closing
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import zlib

ACCOUNT = 'mastervision'
ORIGIN = 'https://shop.mastervision.su'
SITE = 'my-lk.mastervision.su'
MAX_CAPTURE_BYTES = 128 * 1024 * 1024
TABLES = {'meta', 'captures', 'courses', 'events', 'errors', 'course_checkpoints'}
STAGES = {'collect', 'import', 'catalog'}
STATES = {'pending', 'review', 'imported', 'collected', 'empty'}


class StorageError(RuntimeError):
    pass


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def _id(value, *, optional=False):
    return value is None and optional or type(value) is int and 0 < value <= 2**53 - 1


def _key(kind, course, lesson):
    if (kind == 'catalog' and type(course) is int and course == 0 and _id(lesson)
            or kind == 'course' and _id(course) and type(lesson) is int and lesson == 0
            or kind == 'lesson' and _id(course) and _id(lesson)):
        return
    raise StorageError('invalid_capture_identity')


def _codes(codes):
    return isinstance(codes, (tuple, list)) and all(isinstance(code, str) and
        re.fullmatch('[a-z0-9_]{1,100}', code) for code in codes)


def _digest(value):
    return isinstance(value, str) and re.fullmatch('[0-9a-f]{64}', value)


def _unpack(row):
    try:
        stream = zlib.decompressobj()
        raw = stream.decompress(row['payload'], MAX_CAPTURE_BYTES + 1)
        if len(raw) > MAX_CAPTURE_BYTES or not stream.eof or stream.unconsumed_tail or stream.unused_data:
            raise StorageError('capture_compression_invalid')
    except (zlib.error, TypeError): raise StorageError('capture_compression_invalid') from None
    if hashlib.sha256(raw).hexdigest() != row['digest']:
        raise StorageError('source_digest_mismatch')
    try:
        value = json.loads(raw)
        if canonical(value) != raw: raise StorageError('capture_payload_invalid')
    except (ValueError, TypeError, RecursionError): raise StorageError('capture_payload_invalid') from None
    if not isinstance(value, dict) or value.get('account') != ACCOUNT or value.get('origin') != ORIGIN:
        raise StorageError('capture_account_mismatch')
    return value


def _existing(path):
    """Prove ownership read-only before opening a lock or executing any DDL."""
    if path.is_symlink(): raise StorageError('archive_symlink_forbidden')
    if not path.exists(): return
    try:
        with closing(sqlite3.connect(path.as_uri() + '?mode=ro', uri=True, timeout=5)) as db:
            tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}
            if 'meta' not in tables or tables - TABLES: raise StorageError('archive_account_mismatch')
            rows = db.execute('SELECT account,origin,site FROM meta').fetchall()
            if rows != [(ACCOUNT, ORIGIN, SITE)]: raise StorageError('archive_account_mismatch')
    except sqlite3.Error:
        raise StorageError('archive_schema_invalid') from None


class Store:
    def __init__(self, directory):
        self.db = self.lock = None
        if (ACCOUNT, ORIGIN, SITE) != ('mastervision', 'https://shop.mastervision.su', 'my-lk.mastervision.su'):
            raise StorageError('archive_account_mismatch')
        selected = Path(directory)
        if selected.is_symlink(): raise StorageError('archive_symlink_forbidden')
        self.directory = selected.resolve()
        path = self.directory / 'mastervision-migration.sqlite'
        _existing(path)
        # On Windows, ACLs are inherited from the private archive parent. The
        # mode-0700 mkdir special case cannot be reopened by a restricted token.
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o777 if os.name == 'nt' else 0o700)
        if os.name != 'nt':
            if self.directory.stat().st_uid != os.geteuid(): raise StorageError('private_archive_owner_mismatch')
            os.chmod(self.directory, 0o700)
        try:
            lock_path = self.directory / 'worker.lock.sqlite'
            if lock_path.is_symlink(): raise StorageError('archive_symlink_forbidden')
            self.lock = sqlite3.connect(lock_path, timeout=0, isolation_level=None)
            if os.name != 'nt': os.chmod(lock_path, 0o600)
            try:
                self.lock.execute('begin exclusive')
            except sqlite3.OperationalError as exc:
                if getattr(exc, 'sqlite_errorcode', None) in (sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED):
                    raise StorageError('worker_already_running') from None
                raise StorageError('archive_lock_failed') from None
            _existing(path)
            self.db = sqlite3.connect(path, timeout=5)
            if os.name != 'nt': os.chmod(path, 0o600)
            self.db.row_factory = sqlite3.Row
            self.db.executescript('''
        CREATE TABLE IF NOT EXISTS meta(account TEXT,origin TEXT,site TEXT);
        CREATE TABLE IF NOT EXISTS captures(kind TEXT NOT NULL,course INTEGER NOT NULL,
          lesson INTEGER NOT NULL,digest TEXT NOT NULL,at TEXT NOT NULL,payload BLOB NOT NULL,
          PRIMARY KEY(kind,course,lesson,digest));
        CREATE TABLE IF NOT EXISTS courses(id INTEGER PRIMARY KEY,title TEXT NOT NULL,
          lesson_ids TEXT,state TEXT NOT NULL DEFAULT 'pending',source_digest TEXT);
        CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY,at TEXT,stage TEXT,
          course INTEGER,lesson INTEGER,status TEXT,codes TEXT);
        CREATE TABLE IF NOT EXISTS errors(stage TEXT PRIMARY KEY,consecutive INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS course_checkpoints(course INTEGER PRIMARY KEY,
          course_digest TEXT NOT NULL,lesson_digests TEXT NOT NULL);
            ''')
            rows = self.db.execute('SELECT account,origin,site FROM meta').fetchall()
            if not rows:
                self.db.execute('INSERT INTO meta VALUES(?,?,?)', (ACCOUNT, ORIGIN, SITE))
                self.db.commit()
            elif len(rows) != 1 or tuple(rows[0]) != (ACCOUNT, ORIGIN, SITE):
                raise StorageError('archive_account_mismatch')
        except Exception:
            self.close()
            raise

    def close(self):
        db, lock = self.db, self.lock
        self.db = self.lock = None
        try:
            if db is not None: db.close()
        finally:
            if lock is not None:
                try: lock.rollback()
                finally: lock.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    def capture(self, kind, course, lesson, value):
        _key(kind, course, lesson)
        if not isinstance(value, dict) or value.get('account') != ACCOUNT or value.get('origin') != ORIGIN:
            raise StorageError('capture_account_mismatch')
        if shutil.disk_usage(self.directory).free < 256 * 1024 * 1024:
            raise StorageError('insufficient_private_archive_space')
        try: raw = canonical(value)
        except (ValueError, TypeError, RecursionError): raise StorageError('invalid_capture_payload') from None
        if len(raw) > MAX_CAPTURE_BYTES: raise StorageError('capture_too_large')
        digest = hashlib.sha256(raw).hexdigest()
        self.db.execute('INSERT OR IGNORE INTO captures VALUES(?,?,?,?,?,?)',
            (kind, course, lesson, digest, datetime.now(timezone.utc).isoformat(), zlib.compress(raw, 6)))
        self.db.commit()
        return digest

    def latest(self, kind, course, lesson=0):
        _key(kind, course, lesson)
        row = self.db.execute('SELECT payload,digest FROM captures WHERE kind=? AND course=? AND lesson=? ORDER BY at DESC,rowid DESC LIMIT 1',
                              (kind, course, lesson)).fetchone()
        if row is None:
            return None
        return _unpack(row)

    def _exact_verified(self, kind, course, lesson, digest):
        _key(kind, course, lesson)
        if not _digest(digest): raise StorageError('course_checkpoint_invalid')
        row = self.db.execute('SELECT payload,digest FROM captures WHERE kind=? AND course=? AND lesson=? AND digest=?',
                              (kind, course, lesson, digest)).fetchone()
        if row is None: raise StorageError('course_checkpoint_capture_missing')
        value = _unpack(row)
        if value.get('verified') is not True or value.get('error') is not None or not isinstance(value.get('parsed'), dict):
            raise StorageError('course_checkpoint_capture_unverified')
        return value['parsed']

    def _checkpoint_payloads(self, course_id, course_digest, pairs):
        if (not _id(course_id) or not isinstance(pairs, list) or any(not isinstance(pair, (tuple, list))
                or len(pair) != 2 or not _id(pair[0]) or not _digest(pair[1]) for pair in pairs)):
            raise StorageError('course_checkpoint_invalid')
        course = self._exact_verified('course', course_id, 0, course_digest)
        ids = course.get('lesson_ids'); lessons = course.get('lessons'); title = course.get('title')
        if (type(course.get('course_id')) is not int or course['course_id'] != course_id
                or not isinstance(title, str) or not title.strip() or not isinstance(ids, list)
                or any(not _id(ident) for ident in ids) or len(ids) != len(set(ids))
                or not isinstance(lessons, list) or len(lessons) != len(ids)
                or any(not isinstance(row, dict) or type(row.get('id')) is not int or row['id'] != ident
                       or not isinstance(row.get('title'), str) or not row['title'].strip()
                       for ident, row in zip(ids, lessons))):
            raise StorageError('course_checkpoint_identity_mismatch')
        if [pair[0] for pair in pairs] != ids:
            raise StorageError('course_checkpoint_lesson_order_mismatch')
        payloads = []
        for row, (lesson_id, digest) in zip(lessons, pairs):
            lesson = self._exact_verified('lesson', course_id, lesson_id, digest)
            payload = lesson.get('payload')
            if (not isinstance(payload, dict) or payload.get('account') != ACCOUNT or payload.get('source_origin') != ORIGIN
                    or type(payload.get('course_id')) is not int or payload['course_id'] != course_id
                    or type(payload.get('lesson_id')) is not int or payload['lesson_id'] != lesson_id
                    or payload.get('course_title') != title or payload.get('lesson_title') != row['title']
                    or payload.get('format') != 'ape' or not isinstance(payload.get('ape'), dict)
                    or payload['ape'].get('name') != 'page' or not isinstance(payload['ape'].get('children'), list)):
                raise StorageError('course_checkpoint_identity_mismatch')
            payloads.append(payload)
        return course, payloads

    def bind_course(self, course_id, course_digest, lesson_digests):
        """Bind only after the caller's successful live course recheck.

        The checkpoint and course ledger update atomically. Later incomplete or
        unconfirmed captures never replace this exact completed collection.
        """
        record, _ = self._checkpoint_payloads(course_id, course_digest, lesson_digests)
        pairs_json = canonical(lesson_digests).decode()
        with self.db:
            course = self.db.execute('SELECT state,source_digest FROM courses WHERE id=?', (course_id,)).fetchone()
            if course is None: raise StorageError('course_not_in_catalog')
            previous = self.db.execute('SELECT course_digest,lesson_digests FROM course_checkpoints WHERE course=?', (course_id,)).fetchone()
            unchanged = (course['state'] == 'imported' and course['source_digest'] == course_digest and previous is not None
                         and previous['course_digest'] == course_digest and previous['lesson_digests'] == pairs_json)
            self.db.execute('UPDATE courses SET lesson_ids=?,source_digest=?,state=? WHERE id=?',
                (json.dumps(record['lesson_ids']), course_digest, 'imported' if unchanged else 'collected', course_id))
            self.db.execute('INSERT INTO course_checkpoints VALUES(?,?,?) ON CONFLICT(course) DO UPDATE SET '
                            'course_digest=excluded.course_digest,lesson_digests=excluded.lesson_digests',
                            (course_id, course_digest, pairs_json))

    def completed_course(self, course_id):
        """Return payloads from an exact completed checkpoint, never latest()."""
        if not _id(course_id): raise StorageError('invalid_course_capture')
        row = self.db.execute('SELECT course_digest,lesson_digests FROM course_checkpoints WHERE course=?', (course_id,)).fetchone()
        if row is None: raise StorageError('completed_course_checkpoint_missing')
        try: pairs = json.loads(row['lesson_digests'])
        except (ValueError, TypeError): raise StorageError('course_checkpoint_invalid') from None
        record, payloads = self._checkpoint_payloads(course_id, row['course_digest'], pairs)
        ledger = self.db.execute('SELECT source_digest,lesson_ids FROM courses WHERE id=?', (course_id,)).fetchone()
        if ledger is None: raise StorageError('course_not_in_catalog')
        try: ids = json.loads(ledger['lesson_ids'])
        except (ValueError, TypeError): raise StorageError('course_checkpoint_invalid') from None
        if ledger['source_digest'] != row['course_digest'] or ids != record['lesson_ids']:
            raise StorageError('course_checkpoint_source_mismatch')
        return payloads

    def completed_metadata(self, course_id):
        """Return the course metadata from the same verified completed version."""
        self.completed_course(course_id)
        row = self.db.execute('SELECT course_digest FROM course_checkpoints WHERE course=?', (course_id,)).fetchone()
        return self._exact_verified('course', course_id, 0, row['course_digest'])

    def completed_snapshot(self, course_id):
        """Return the original private course page bound to its checkpoint."""
        self.completed_course(course_id)
        row = self.db.execute('''SELECT c.payload,c.digest FROM captures c
          JOIN course_checkpoints p ON p.course=c.course AND p.course_digest=c.digest
          WHERE c.kind='course' AND c.course=? AND c.lesson=0''', (course_id,)).fetchone()
        if row is None: raise StorageError('course_checkpoint_capture_missing')
        return _unpack(row)

    def catalog(self, courses):
        if not isinstance(courses, list) or any(not isinstance(course, dict) or not _id(course.get('id'))
                or not isinstance(course.get('title'), str) or not course['title'].strip() for course in courses):
            raise StorageError('invalid_catalog_identity')
        ids = [course['id'] for course in courses]
        if len(set(ids)) != len(ids):
            raise StorageError('duplicate_catalog_identity')
        with self.db:
            for course in courses:
                self.db.execute('INSERT INTO courses(id,title) VALUES(?,?) ON CONFLICT(id) DO UPDATE SET title=excluded.title',
                                (course['id'], course['title']))

    def course(self, course_id, lesson_ids, digest):
        if (not _id(course_id) or not isinstance(lesson_ids, list) or any(not _id(x) for x in lesson_ids)
                or len(lesson_ids) != len(set(lesson_ids)) or not isinstance(digest, str)
                or not re.fullmatch('[0-9a-f]{64}', digest)):
            raise StorageError('invalid_course_capture')
        if not self.db.execute("SELECT 1 FROM captures WHERE kind='course' AND course=? AND lesson=0 AND digest=?", (course_id, digest)).fetchone():
            raise StorageError('unknown_course_capture')
        with self.db:
            changed = self.db.execute("UPDATE courses SET lesson_ids=?,source_digest=?,state=CASE WHEN source_digest=? AND state='imported' THEN state ELSE 'collected' END WHERE id=?",
                        (json.dumps(lesson_ids), digest, digest, course_id))
            if changed.rowcount != 1: raise StorageError('course_not_in_catalog')

    def mark(self, course_id, state):
        if not _id(course_id) or not isinstance(state, str) or state not in STATES - {'pending'}:
            raise StorageError('invalid_course_state')
        with self.db:
            if self.db.execute('UPDATE courses SET state=? WHERE id=?', (state, course_id)).rowcount != 1:
                raise StorageError('course_not_in_catalog')

    def event(self, stage, course, lesson, status, codes=()):
        if (not isinstance(stage, str) or stage not in STAGES or not isinstance(status, str) or not re.fullmatch('[a-z_]{1,60}', status)
                or not _codes(codes) or not _id(course, optional=True) or not _id(lesson, optional=True)):
            raise StorageError('unsafe_diagnostic')
        self.db.execute('INSERT INTO events(at,stage,course,lesson,status,codes) VALUES(?,?,?,?,?,?)',
            (datetime.now(timezone.utc).isoformat(), stage, course, lesson, status, json.dumps(list(codes))))
        self.db.commit()

    def error(self, stage, failed):
        if not isinstance(stage, str) or stage not in STAGES or type(failed) is not bool: raise StorageError('unsafe_diagnostic')
        self.db.execute('INSERT INTO errors VALUES(?,?) ON CONFLICT(stage) DO UPDATE SET consecutive=CASE WHEN ? THEN consecutive+1 ELSE 0 END',
                        (stage, int(failed), int(failed)))
        self.db.commit()
        return self.db.execute('SELECT consecutive FROM errors WHERE stage=?', (stage,)).fetchone()[0]

    def summary(self):
        rows = self.db.execute('SELECT state,COUNT(*) FROM courses GROUP BY state').fetchall()
        if any(row[0] not in STATES for row in rows): raise StorageError('archive_state_invalid')
        return {row[0]: row[1] for row in rows}

    def report(self):
        summary = self.summary()
        lines = ['# Перенос курсов и уроков МВ', '', 'Источник: https://shop.mastervision.su',
                 'Назначение: https://my-lk.mastervision.su', '', '## Состояние', '']
        lines += [f'- {key}: {value}' for key, value in sorted(summary.items())]
        lines += ['', '## Требуют разбора', '']
        rows = self.db.execute('''SELECT e.course,e.lesson,e.stage,e.codes FROM events e
          WHERE e.status='review' AND e.id=(SELECT MAX(x.id) FROM events x WHERE
          x.course=e.course AND x.stage=e.stage AND x.lesson IS e.lesson)
          AND EXISTS(SELECT 1 FROM courses c WHERE c.id=e.course AND
            (c.state='review' OR (c.state='imported' AND e.lesson IS NULL)))
          ORDER BY e.course,e.lesson''').fetchall()
        for row in rows:
            lesson = row['lesson']
            try: codes = json.loads(row['codes'])
            except (ValueError, TypeError): raise StorageError('unsafe_diagnostic') from None
            if row['stage'] not in STAGES or not _id(row['course']) or not _id(lesson, optional=True) or not _codes(codes):
                raise StorageError('unsafe_diagnostic')
            url = (ORIGIN + '/shop/training/traininglessons/admin/update?id=' + str(lesson) + '&lg=ru') if lesson else (
                   ORIGIN + '/shop/training/admin/update?id=' + str(row['course']) + '&lg=ru')
            lines.append(f"- Курс {row['course']}" + (f", урок {lesson}" if lesson else '') +
                         f": [{row['stage']}]({url}) — {', '.join(codes)}")
        if not rows:
            lines.append('Проблемы ещё не зарегистрированы.')
        path = self.directory / 'ОТЧЁТ-перенос-mastervision.md'
        temporary = path.with_name(path.name + '.tmp-' + os.urandom(6).hex())
        fd = os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as stream:
                stream.write('\n'.join(lines) + '\n'); stream.flush(); os.fsync(stream.fileno())
            os.replace(temporary, path)
        finally:
            if temporary.exists(): temporary.unlink()
        return path

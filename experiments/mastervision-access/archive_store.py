"""Resumable, isolated Master Vision access-card archive. No application database writes."""
import argparse
from contextlib import closing
from datetime import datetime, timedelta, timezone
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import sys
import tempfile
import zlib


ORIGIN = 'https://shop.mastervision.su'
ACCOUNT = 'mastervision'
BOUND = 446858
BASE = Path('/home/frappe/frappe-bench/sites/my-lk.mastervision.su/private/mv-course-access')
FOLDER = BASE / 'through-446858-20261120'
RESERVE = 384 * 1024 * 1024
MAX_WIRE = 24 * 1024 * 1024
MAX_RAW = 72 * 1024 * 1024
MAX_POLICY = 2 * 1024 * 1024
POLICY_START = datetime(2026, 11, 20, tzinfo=timezone(timedelta(hours=3)))
SCHEMA = """
CREATE TABLE IF NOT EXISTS metadata(key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS configs(sha TEXT PRIMARY KEY, payload BLOB NOT NULL);
CREATE TABLE IF NOT EXISTS cards(link_id INTEGER PRIMARY KEY,contact_id INTEGER NOT NULL,
    course_id INTEGER NOT NULL,captured_at TEXT NOT NULL,config_sha TEXT NOT NULL REFERENCES configs(sha),
    detail BLOB NOT NULL);
CREATE INDEX IF NOT EXISTS card_pair ON cards(contact_id,course_id,link_id);
CREATE TABLE IF NOT EXISTS missing(link_id INTEGER PRIMARY KEY, captured_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS problems(link_id INTEGER PRIMARY KEY, code TEXT NOT NULL, attempts INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS inventory(link_id INTEGER PRIMARY KEY);
"""


def utc():
    return datetime.now(timezone.utc).isoformat()


def packed(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def check(ok, code):
    if not ok:
        raise ValueError(code)


def number(value, cap=2**53-1):
    check(type(value) is int and 0 < value <= cap, 'bad_id')
    return value


def get(db, key):
    row = db.execute('select value from metadata where key=?', (key,)).fetchone()
    return row[0] if row else None


def put(db, key, value):
    db.execute('insert or replace into metadata values(?,?)', (key, value))


def connect(path):
    db = sqlite3.connect(path, timeout=20)
    db.execute('PRAGMA foreign_keys=ON')
    db.execute('PRAGMA journal_mode=WAL')
    db.executescript(SCHEMA)
    identity = {'origin': ORIGIN, 'account': ACCOUNT, 'through': str(BOUND), 'schema': '1'}
    with db:
        if get(db,'account') is None:
            db.executemany('insert into metadata values (?,?)', identity.items())
            put(db,'capture_state','collecting')
            put(db,'started_at',utc())
        check(all(get(db,k)==v for k,v in identity.items()), 'archive_mismatch')
    return db


def save(db, records):
    check(type(records) is list and 0 < len(records) <= 100, 'batch_size')
    check(get(db,'capture_state') != 'complete', 'archive_already_complete')
    with db:
        for r in records:
            ident = number(r['id'], BOUND)
            if r['status']=='error':
                check(re.fullmatch(r'[a-z_]{1,80}',r['code']), 'invalid_error_code')
                db.execute('insert into problems values(?,?,1) on conflict(link_id) do update set code=excluded.code, attempts=attempts+1',
                           (ident,r['code']))
                continue
            check(r['origin']==ORIGIN, 'origin_mismatch')
            timestamp = r['captured_at']
            check(datetime.fromisoformat(timestamp.replace('Z','+00:00')).utcoffset() is not None, 'timestamp')
            if r['status']=='missing':
                check(not db.execute('select 1 from cards where link_id=?',(ident,)).fetchone(),'changed_during_capture')
                db.execute('insert or ignore into missing values(?,?)',(ident,timestamp))
            else:
                check(r['status']=='card' and not db.execute('select 1 from missing where link_id=?',(ident,)).fetchone(), 'changed_during_capture')
                all_rows,detail=r['allLessons'],r['detail']
                number(r['contact_id'])
                check(number(r['course_id'])==number(detail['course']['id']), 'course_mismatch')
                allowed_ids={number(x['id']) for x in all_rows}
                assigned=[number(x['id']) for x in detail['availableLessons']]
                check(len(allowed_ids)==len(all_rows) and len(set(assigned))==len(assigned)
                      and set(assigned)<=allowed_ids,'lesson_ids')
                config=packed(all_rows)
                digest=hashlib.sha256(config).hexdigest()
                if not db.execute('select 1 from configs where sha=?',(digest,)).fetchone():
                    db.execute('insert into configs values(?,?)',(digest,zlib.compress(config,4)))
                old=db.execute('select contact_id,course_id from cards where link_id=?',(ident,)).fetchone()
                check(old in (None,(r['contact_id'],r['course_id'])), 'identity_changed')
                db.execute('insert or replace into cards values(?,?,?,?,?,?)',
                           (ident,r['contact_id'],r['course_id'],timestamp,digest,zlib.compress(packed(detail),4)))
            db.execute('delete from problems where link_id=?',(ident,))
        put(db,'updated_at',utc())


def resume(db):
    ids=[x[0] for x in db.execute('select link_id from cards union select link_id from missing order by 1')]
    ranges=[]
    for ident in ids:
        if ranges and ranges[-1][1]+1==ident:
            ranges[-1][1]=ident
        else:
            ranges.append([ident,ident])
    return ranges


def status(db):
    return {'state':get(db,'capture_state'), 'cards':db.execute('select count(*) from cards').fetchone()[0],
            'missing':db.execute('select count(*) from missing').fetchone()[0],
            'problems':db.execute('select count(*) from problems').fetchone()[0],
            'updated_at':get(db,'updated_at'),'scope':get(db,'scope') or 'range'}


def validate_policy(policy, ident):
    check(isinstance(policy,dict) and policy.get('source_origin')==ORIGIN, 'wrong_policy_origin')
    check(number(policy.get('course_id'))==ident, 'wrong_policy_course')
    check(isinstance(policy.get('no_access_info'),dict) and isinstance(policy.get('settings'),dict), 'policy_structure')
    drafts=policy.get('draft_lesson_ids')
    check(isinstance(drafts,list) and len(drafts)<=5000 and
          all(number(i) for i in drafts) and len(set(drafts))==len(drafts), 'policy_draft_lessons')
    try:
        captured=datetime.fromisoformat(policy['captured_at'].replace('Z','+00:00'))
        check(captured.utcoffset() is not None and POLICY_START<=captured<=datetime.now(timezone.utc)+timedelta(minutes=5),
              'policy_timestamp')
    except (KeyError,ValueError,TypeError,AttributeError):
        raise ValueError('policy_timestamp') from None
    return captured


def read_policy(path, ident):
    check(not path.is_symlink() and path.stat().st_size<=MAX_POLICY, 'policy_file')
    value=json.loads(path.read_bytes())
    return validate_policy(value,ident)


def policies(db, msg):
    directory=FOLDER/'policies'
    check(not directory.is_symlink(), 'policy_directory')
    if msg['op']=='policy_ids':
        needed=[]
        for (ident,) in db.execute('select distinct course_id from cards order by course_id'):
            try:
                read_policy(directory/(str(ident)+'.json'),ident)
            except (FileNotFoundError,ValueError):
                needed.append(ident)
        return {'course_ids':needed}
    value=msg['policy']
    ident=number(value.get('course_id'))
    captured=validate_policy(value,ident)
    raw=packed(value)
    check(len(raw)<=MAX_POLICY, 'policy_size')
    check(shutil.disk_usage(FOLDER).free>=RESERVE, 'disk_reserve')
    directory.mkdir(mode=0o700,exist_ok=True)
    path=directory/(str(ident)+'.json')
    if path.exists():
        check(not path.is_symlink(), 'policy_file')
        try:
            previous=read_policy(path,ident)
        except ValueError:
            previous=None  # Recover malformed/stale data using a full fresh course policy.
        check(previous is None or captured>=previous, 'older_policy')
    tmp=None
    try:
        with tempfile.NamedTemporaryFile(mode='wb',dir=directory,prefix='.course-',delete=False) as file:
            tmp=Path(file.name)
            os.chmod(tmp,0o600)
            file.write(raw)
            file.flush()
            os.fsync(file.fileno())
        os.replace(tmp,path)
    finally:
        if tmp and tmp.exists():
            tmp.unlink()
    return {'stored':True,'course_id':ident}


def respond(db, msg):
    cmd=msg['op']
    if cmd in ('policy','policy_ids'):
        return policies(db,msg)
    if cmd=='status':
        return status(db)
    if cmd=='resume':
        return {'ranges':resume(db),**status(db)}
    if cmd=='batch':
        check(shutil.disk_usage(FOLDER).free>=RESERVE, 'disk_reserve')
        dec=zlib.decompressobj()
        raw=dec.decompress(base64.b64decode(msg['data'],validate=True),MAX_RAW+1)
        check(len(raw)<=MAX_RAW and dec.eof and not dec.unused_data and not dec.unconsumed_tail, 'bad_batch')
        save(db,json.loads(raw))
        return {'stored':True}
    if cmd=='inventory':
        # The caller proves this is the complete bounded administrator listing.
        # Both passes must return exactly the same unique IDs before we use it.
        first,second=msg['first'],msg['second']
        check(get(db,'capture_state')!='complete' and first==second and
              first==sorted(set(first)) and BOUND in first, 'inventory_changed')
        check(all(number(x,BOUND) for x in first), 'bad_id')
        with db:
            db.execute('delete from inventory')
            db.executemany('insert into inventory values(?)',((i,) for i in first))
            put(db,'scope','inventory')
            put(db,'inventory_at',utc())
        return {'listed':len(first)}
    if cmd=='finish':
        s=status(db)
        check(not s['problems'], 'unresolved_cards')
        if s['scope']=='inventory':
            check(db.execute('select count(*) from inventory').fetchone()[0]==s['cards'] and
                  not db.execute('select link_id from inventory except select link_id from cards limit 1').fetchone(),
                  'incomplete_inventory')
        else:
            check(s['cards']+s['missing']==BOUND,'incomplete_range')
        check(db.execute('select count(*) from cards where link_id in (446462,446858)').fetchone()[0]==2,'controls_missing')
        with db:
            put(db,'capture_state','complete')
            put(db,'completed_at',utc())
        return status(db)
    raise ValueError('unknown_command')


def main():
    import fcntl  # Only the live Linux receiver needs a process lock.
    parser=argparse.ArgumentParser()
    parser.add_argument('--status',action='store_true')
    args=parser.parse_args()
    path=FOLDER/'cards.sqlite'
    if args.status:
        with closing(sqlite3.connect(path.as_uri()+'?mode=ro',uri=True)) as db:
            print(json.dumps(status(db)))
        return
    os.umask(0o077)
    FOLDER.mkdir(parents=True,exist_ok=True,mode=0o700)
    with (FOLDER/'collector.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        with closing(connect(path)) as db:
            while True:
                line=sys.stdin.buffer.readline(MAX_WIRE+1)
                if not line:
                    return
                check(len(line)<=MAX_WIRE, 'packet_limit')
                print(json.dumps(respond(db,json.loads(line)),separators=(',',':')),flush=True)


if __name__=='__main__':
    try:
        main()
    except Exception as e:
        print(json.dumps({'error':str(e) if re.fullmatch(r'[a-z_]+',str(e)) else 'archive_error'}),flush=True)
        raise SystemExit(1)

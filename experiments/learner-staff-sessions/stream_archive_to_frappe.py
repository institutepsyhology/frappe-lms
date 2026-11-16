"""Small MVC-only sidecar: verified remote archive before local payload eviction.

The AVO key stays in the untouched running reader. Payloads travel only in SSH
stdin, never argv/files/logs. This archives source data; it does not activate login.
"""
from contextlib import closing
from datetime import datetime, timezone
import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import sqlite3
import subprocess
import time
import zlib

from audit_legacy_links import API_ORIGIN
from collect_personal_links import verified_link
from collect_personal_links_bulk import writer_lock, validate_remote_receipts
from legacy_api_snapshot import FORMAT as SOURCE_FORMAT, unprotect_page
from private_link_storage import unprotect_url
from progress_io import read_json, write_json
from server_archive_sink import SAFE_CODES as REMOTE_CODES, PROFILE

FORMAT = PROFILE.wire_format
SITE = PROFILE.site
REMOTE_PREFIX = PROFILE.remote_prefix
HERE = Path(__file__).resolve().parent
WORKSPACE = HERE.parents[2]
BENCH = '/home/frappe/frappe-bench'


class DeliveryError(Exception): pass


def canonical(value):
    return json.dumps(value,ensure_ascii=True,sort_keys=True,separators=(',',':')).encode('utf-8')


def stamp(): return datetime.now(timezone.utc).isoformat()


def checked_file(path):
    path = Path(path)
    if not path.is_file() or path.is_symlink() or path.stat().st_nlink != 1:
        raise DeliveryError('unsafe_local_path')
    return path


def open_links(path, snapshot):
    checked_file(path)
    if not re.fullmatch('[a-f0-9]{32}',snapshot): raise DeliveryError('wrong_snapshot')
    db = sqlite3.connect(path,timeout=5)
    try:
        db.execute('PRAGMA foreign_keys=ON')
        db.execute('PRAGMA synchronous=FULL')
        meta = dict(db.execute('SELECT key,value FROM metadata'))
        if (meta.get('schema') != PROFILE.link_schema or meta.get('account') != PROFILE.account
                or meta.get('origin') != API_ORIGIN): raise DeliveryError('wrong_source')
        db.execute('''CREATE TABLE IF NOT EXISTS delivery_receipts (
            version_id INTEGER PRIMARY KEY REFERENCES links(version_id),snapshot TEXT NOT NULL,
            sha256 TEXT NOT NULL,target TEXT NOT NULL,ack_at TEXT NOT NULL,payload_bytes INTEGER NOT NULL)''')
        db.commit()
        if db.execute('SELECT 1 FROM delivery_receipts WHERE snapshot<>? OR target<>? LIMIT 1',
                      (snapshot,SITE)).fetchone(): raise DeliveryError('wrong_receipt_target')
        validate_remote_receipts(db)
        return db
    except BaseException:
        db.close()
        raise


def wrap(version, ident, payload):
    raw = canonical(payload)
    return {'version_id':version,'source_id':ident,'sha256':hashlib.sha256(raw).hexdigest(),
            'payload_b64':base64.b64encode(raw).decode('ascii')}


def request_for(snapshot,kind,metadata,records):
    return {'format':FORMAT,'snapshot':snapshot,'kind':kind,'source_metadata':metadata,'records':records}


def link_batch(db, snapshot):
    try: validate_remote_receipts(db)
    except Exception: raise DeliveryError('invalid_remote_reference') from None
    cursor = db.execute('SELECT COALESCE(MAX(version_id),0) FROM delivery_receipts').fetchone()[0]
    if db.execute('''SELECT 1 FROM links l LEFT JOIN delivery_receipts r ON r.version_id=l.version_id
        WHERE l.version_id<=? AND r.version_id IS NULL LIMIT 1''',(cursor,)).fetchone():
        raise DeliveryError('delivery_receipt_gap')
    # fetchall ends the read cursor before decryption/SSH, so WAL checkpointing
    # and the producer's next commit are not held up by the network request.
    rows = db.execute('''SELECT version_id,source_id,url_encrypted,token_digest,captured_at,
        source_field,capture_origin FROM links WHERE version_id>? ORDER BY version_id LIMIT 100''',
        (cursor,)).fetchall()
    if not rows: return None
    records = []
    for version,ident,encrypted,digest,captured,field,origin in rows:
        try:
            url = unprotect_url(ident,encrypted)
            _, actual = verified_link(ident,{'link_personal_auth':url})
            if actual != digest: raise DeliveryError('local_link_digest_mismatch')
        except Exception: raise DeliveryError('invalid_local_link') from None
        records.append(wrap(version,ident,{'version_id':version,'source_id':ident,'url':url,
            'token_digest':digest.hex(),'captured_at':captured,'source_field':field,'capture_origin':origin}))
    return request_for(snapshot,'links',dict(db.execute('SELECT key,value FROM metadata')),records)


def verify_ack(request, ack):
    expected = [{key:row[key] for key in ('version_id','source_id','sha256')} for row in request['records']]
    if (not isinstance(ack,dict) or set(ack) != {'format','site','snapshot','kind','records','stored_total'}
            or ack['format'] != FORMAT or ack['site'] != SITE or ack['snapshot'] != request['snapshot']
            or ack['kind'] != request['kind'] or ack['records'] != expected
            or type(ack['stored_total']) is not int or ack['stored_total'] < len(expected)):
        raise DeliveryError('remote_ack_mismatch')


def ack_links(db, request, ack):
    verify_ack(request,ack)
    # Receipt and explicit reference replace the ciphertext in ONE local commit.
    # Keep rows/FKs/digests/cursors, including older versions of the same contact.
    with db:
        for row in request['records']:
            version,ident,digest = row['version_id'],row['source_id'],row['sha256']
            marker = REMOTE_PREFIX + f'{request["snapshot"]}:{version}:{digest}'.encode('ascii')
            old = db.execute('SELECT source_id,url_encrypted FROM links WHERE version_id=?',(version,)).fetchone()
            if not old or old[0] != ident: raise DeliveryError('local_version_changed')
            prior = db.execute('SELECT snapshot,sha256,target FROM delivery_receipts WHERE version_id=?',(version,)).fetchone()
            if prior:
                if prior != (request['snapshot'],digest,SITE) or old[1] != marker:
                    raise DeliveryError('local_receipt_conflict')
                continue
            # Bind the acknowledged body to the exact source row about to evict.
            payload = json.loads(base64.b64decode(row['payload_b64'],validate=True))
            if (hashlib.sha256(base64.b64decode(row['payload_b64'],validate=True)).hexdigest() != digest
                    or unprotect_url(ident,old[1]) != payload['url']):
                raise DeliveryError('local_version_changed')
            db.execute('INSERT INTO delivery_receipts VALUES (?,?,?,?,?,?)',
                (version,request['snapshot'],digest,SITE,stamp(),len(old[1])))
            db.execute('UPDATE links SET url_encrypted=? WHERE version_id=?',(marker,version))


def ssh_arguments(program):
    wrapper = ("import base64,sys;n={'__name__':'mvc_private_archive'};exec(compile(base64.b64decode('"
        + base64.b64encode(program.encode('utf-8')).decode('ascii')
        + "'),'<mvc-private-archive>','exec'),n);sys.exit(n['main']())")
    command = shlex.join(['docker','exec','-i','-u','frappe','-w',BENCH+'/sites',
        'company-lms-backend-1',BENCH+'/env/bin/python','-B','-c',wrapper])
    return ['ssh','-o','BatchMode=yes','-o','ConnectTimeout=15','-o','ServerAliveInterval=15',
        '-o','ServerAliveCountMax=2','-o','StrictHostKeyChecking=yes',
        '-o','UserKnownHostsFile='+str(WORKSPACE/'frappe-deploy/known_hosts'),
        '-i',str(Path.home()/'.ssh/codex_timeweb_lms_20261010'),'root@89.223.71.30',command]


def remote(request):
    program = (HERE/'server_archive_sink.py').read_text(encoding='utf-8')
    try:
        result = subprocess.run(ssh_arguments(program),input=canonical(request),stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,timeout=90,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        if len(result.stdout)>1024*1024: raise DeliveryError('remote_response_too_large')
        value = json.loads(result.stdout)
    except (OSError,subprocess.SubprocessError,ValueError,UnicodeError):
        raise DeliveryError('remote_result_uncertain') from None
    if result.returncode:
        code=value.get('error') if isinstance(value,dict) else None
        raise DeliveryError('remote_'+code if code in REMOTE_CODES else 'remote_rejected_batch')
    verify_ack(request,value)
    return value


def page_batch(db, state, snapshot):
    previous = state.execute('SELECT COALESCE(MAX(version_id),0) FROM page_receipts').fetchone()[0]
    names = [item[1] for item in db.execute('PRAGMA table_info(pages)')]
    records,total=[],0
    cursor=db.execute('SELECT * FROM pages WHERE version_id>? ORDER BY version_id LIMIT 20',(previous,))
    try:
        for row in cursor:
            payload = dict(zip(names,row))
            encrypted = payload.pop('raw_encrypted')
            envelope = unprotect_page(payload['resource'],payload['page'],encrypted)
            if envelope['snapshot'] != snapshot or envelope['sha256'] != payload['sha256']:
                raise DeliveryError('invalid_local_page')
            payload['body_b64'] = base64.b64encode(zlib.compress(envelope['raw'],6)).decode('ascii')
            record=wrap(payload['version_id'],None,payload)
            size=len(canonical(record))
            if records and total+size>4*1024*1024: break
            records.append(record);total+=size
    finally: cursor.close()
    if not records:return None
    return request_for(snapshot,'pages',dict(db.execute('SELECT key,value FROM metadata')),records)


def directories(job):
    original = Path(job)
    if original.is_symlink(): raise DeliveryError('unsafe_local_path')
    job = original.resolve(strict=True)
    if any((p/'.git').exists() for p in (job,*job.parents)): raise DeliveryError('private_directory_required')
    checked_file(job/'snapshot.sqlite')
    with closing(sqlite3.connect((job/'snapshot.sqlite').as_uri()+'?mode=ro',uri=True)) as db:
        meta = dict(db.execute('SELECT key,value FROM metadata'))
    snapshot = meta.get('snapshot','')
    if (meta.get('format')!=SOURCE_FORMAT or meta.get('account')!=PROFILE.account
            or meta.get('source')!=API_ORIGIN or not re.fullmatch('[a-f0-9]{32}',snapshot)):
        raise DeliveryError('wrong_source')
    links = job/('links-'+snapshot)
    if links.is_symlink(): raise DeliveryError('unsafe_local_path')
    checked_file(links/'links.sqlite')
    folder = job/'delivery'
    if folder.is_symlink(): raise DeliveryError('unsafe_local_path')
    folder.mkdir(exist_ok=True)
    for name in ('progress.json','progress.json.tmp','state.sqlite','state.sqlite-journal','STOP','collector.lock'):
        p=folder/name
        if p.exists() and (p.is_symlink() or not p.is_file() or p.stat().st_nlink!=1):
            raise DeliveryError('unsafe_local_path')
    return job,links,folder,snapshot


def stop_reader(job, reason):
    try:
        with (job/'STOP').open('x',encoding='ascii') as stream:
            stream.write('mvc-archive-delivery: '+reason)
            stream.flush();os.fsync(stream.fileno())
    except FileExistsError: pass


def run(job, *, once=False, transport=remote, pause=time.sleep):
    job,links,folder,snapshot = directories(job)
    report = {'status':'initializing','site':SITE,'snapshot':snapshot,'links_delivered':0,
        'pages_delivered':0,'pending_links':0,'consecutive_failures':0,'error_code':None,
        'local_ciphertext_bytes_released':0,'source_reader_restarted':False,'credentials_saved':False}
    with writer_lock(folder), closing(sqlite3.connect(folder/'state.sqlite')) as state:
        state.execute('PRAGMA synchronous=FULL')
        state.execute('CREATE TABLE IF NOT EXISTS page_receipts (version_id INTEGER PRIMARY KEY,sha256 TEXT NOT NULL)')
        state.commit()
        while not (folder/'STOP').exists():
            if shutil.disk_usage(job).free < 128*1024*1024:
                stop_reader(job,'local_space_critical')
                report.update(status='stopped',error_code='local_space_critical')
                write_json(folder/'progress.json',dict(report,updated_at=stamp()))
                return report
            try:
                activity = False
                with closing(open_links(links/'links.sqlite',snapshot)) as db:
                    batch = link_batch(db,snapshot)
                    if batch:
                        ack_links(db,batch,transport(batch))
                        activity = True
                    report['links_delivered'],report['local_ciphertext_bytes_released'] = db.execute(
                        'SELECT COUNT(*),COALESCE(SUM(payload_bytes),0) FROM delivery_receipts').fetchone()
                    report['pending_links'] = db.execute('SELECT COUNT(*) FROM links').fetchone()[0]-report['links_delivered']
                with closing(sqlite3.connect((job/'snapshot.sqlite').as_uri()+'?mode=ro',uri=True,timeout=5)) as db:
                    batch = page_batch(db,state,snapshot)
                if batch:
                    verify_ack(batch,transport(batch))
                    with state:
                        state.executemany('INSERT OR IGNORE INTO page_receipts VALUES (?,?)',
                            ((row['version_id'],row['sha256']) for row in batch['records']))
                    activity = True
                report['pages_delivered'] = state.execute('SELECT COUNT(*) FROM page_receipts').fetchone()[0]
                report.update(status='following' if not activity else 'delivering',consecutive_failures=0,error_code=None)
            except Exception as error:
                report['consecutive_failures'] += 1
                report['error_code'] = (error.args[0] if isinstance(error,DeliveryError) else 'delivery_failed')
                report['status'] = 'retry_wait'
                if report['consecutive_failures'] >= 10:
                    stop_reader(job,'ten_delivery_failures')
                    report['status'] = 'stopped'
            write_json(folder/'progress.json',dict(report,updated_at=stamp()))
            if once or report['status']=='stopped': return report
            if not activity and report['status']=='following':
                source_progress=read_json(links/'progress.json')
                if source_progress.get('status') in {'completed','completed_with_failures'}:
                    report['status']='completed'
                    write_json(folder/'progress.json',dict(report,updated_at=stamp()))
                    return report
            pause(15 if report['status']=='retry_wait' else 0.2 if activity else 5)
        report['status']='cancelled'
        write_json(folder/'progress.json',dict(report,updated_at=stamp()))
    return report


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--job-directory',required=True,type=Path)
    parser.add_argument('--once',action='store_true')
    args=parser.parse_args()
    try: report=run(args.job_directory,once=args.once)
    except Exception: report={'status':'stopped','error_code':'delivery_initialization_failed'}
    print(json.dumps(report,ensure_ascii=True))
    return 0 if report['status'] not in {'stopped','retry_wait'} else 1


if __name__=='__main__': raise SystemExit(main())

"""Capture individual MV API profiles and links for one ID-only selection.

The general MV/IOMP jobs remain stopped. No source key, plaintext profile,
password, or personal URL is ever written to the log. No link is redeemed.
"""
import argparse
from contextlib import closing,redirect_stdout,redirect_stderr
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import time
import zlib

from apply_server_contacts import (ApplyError,private,safe_file,selection_path,
    read_selection,verify_release,stamp,lock)

ACCOUNT='mastervision'
SITE='my-lk.mastervision.su'
ORIGIN='https://shop.mastervision.su'
API_RELEASE='8256ed1d520cd77d7eddfe5cecd1bb2d99c3c74e'
BENCH=Path('/home/frappe/frappe-bench')


def write_status(folder,**value):
    value.update(account=ACCOUNT,site=SITE,key_saved=False,updated_at=stamp())
    path=safe_file(folder/'server-status.json');tmp=safe_file(folder/'server-status.tmp')
    fd=os.open(tmp,os.O_WRONLY|os.O_CREAT|os.O_TRUNC|os.O_NOFOLLOW,0o600)
    with os.fdopen(fd,'w') as stream:
        json.dump(value,stream,sort_keys=True);stream.flush();os.fsync(stream.fileno())
    os.replace(tmp,path)


def open_profiles(folder,fingerprint):
    path=safe_file(folder/'profiles.sqlite')
    fd=os.open(path,os.O_RDWR|os.O_CREAT|os.O_NOFOLLOW,0o600);os.close(fd)
    db=sqlite3.connect(path)
    db.execute('PRAGMA synchronous=FULL')
    db.executescript('''CREATE TABLE IF NOT EXISTS metadata(key TEXT PRIMARY KEY,value TEXT);
      CREATE TABLE IF NOT EXISTS profiles(source_id INTEGER PRIMARY KEY,sha256 TEXT NOT NULL,
        encrypted BLOB NOT NULL,captured_at TEXT NOT NULL);
      CREATE TABLE IF NOT EXISTS source_optouts(source_id INTEGER PRIMARY KEY);''')
    expected={'format':'selected-mv-profile-v1','account':ACCOUNT,'site':SITE,'selection':fingerprint}
    actual=dict(db.execute('SELECT key,value FROM metadata'))
    if actual and actual!=expected:db.close();raise ApplyError('profile_identity_mismatch')
    if not actual:
        with db:db.executemany('INSERT INTO metadata VALUES (?,?)',expected.items())
    return db


def save_profile(db,cipher,fingerprint,ident,detail,key,reject_leak,*,optout=False):
    if (type(ident) is not int or not 0<ident<2**63 or type(detail) is not dict
            or str(detail.get('id_contact'))!=str(ident)):
        raise ApplyError('profile_identity_mismatch')
    raw=json.dumps(detail,ensure_ascii=True,sort_keys=True,separators=(',',':'),allow_nan=False).encode()
    if len(raw)>4*1024**2:raise ApplyError('profile_too_large')
    reject_leak(raw,key)
    digest=hashlib.sha256(raw).hexdigest()
    envelope={'format':'selected-mv-profile-v1','account':ACCOUNT,'site':SITE,
        'selection':fingerprint,'source_id':ident,'sha256':digest,'profile':detail}
    encrypted=cipher.encrypt(zlib.compress(json.dumps(envelope,sort_keys=True,ensure_ascii=True,
        separators=(',',':'),allow_nan=False).encode(),6))
    if json.loads(zlib.decompress(cipher.decrypt(encrypted)))!=envelope:
        raise ApplyError('profile_readback_failed')
    with db:
        db.execute('INSERT INTO profiles VALUES (?,?,?,?) ON CONFLICT(source_id) DO UPDATE SET '
            'sha256=excluded.sha256,encrypted=excluded.encrypted,captured_at=excluded.captured_at',
            (ident,digest,encrypted,stamp()))
        if optout:db.execute('INSERT OR IGNORE INTO source_optouts VALUES (?)',(ident,))
    saved=db.execute('SELECT sha256,encrypted FROM profiles WHERE source_id=?',(ident,)).fetchone()
    if not saved or saved[0]!=digest or saved[1]!=encrypted:raise ApplyError('profile_readback_failed')


def initialize_api():
    for variable in ('AVO_ARCHIVE_ACCOUNT','AVO_SERVER_ARCHIVE_ACCOUNT'):
        if os.environ.get(variable,ACCOUNT)!=ACCOUNT:raise ApplyError('wrong_account')
        os.environ[variable]=ACCOUNT
    api=BENCH/'sites'/SITE/'private/avo-api-archive'/('release-'+API_RELEASE)
    sys.path.insert(0,str(api))
    import server_archive_job
    if server_archive_job.verify_release()!=API_RELEASE:raise ApplyError('invalid_release')
    profile=server_archive_job.bound_runtime()
    if profile.account!=ACCOUNT or profile.site!=SITE or profile.api_origin!=ORIGIN:
        raise ApplyError('wrong_account')


def run(fingerprint,key):
    selected,folder=read_selection(ACCOUNT,fingerprint)
    output=folder/'individual';private(output)
    initialize_api()
    import frappe
    from cryptography.fernet import Fernet
    from collect_personal_links import read_detail
    from collect_personal_links_bulk import collect
    from legacy_api_snapshot import reject_key_leak
    frappe.init(site=SITE);frappe.connect();frappe.set_user('Administrator')
    try:
        cipher=Fernet(frappe.conf.encryption_key.encode())
        with closing(open_profiles(output,fingerprint)) as profiles:
            def fetch(secret,ident):
                if str(ident) not in selected:raise ApplyError('outside_selection')
                # Reserve disk before even issuing another source request.
                import shutil
                while shutil.disk_usage(output).free<2*1024**3:
                    if (folder/'STOP').exists() or (output/'STOP').exists():
                        from collect_personal_links_bulk import Cancelled
                        raise Cancelled()
                    write_status(output,status='waiting_for_space',worker_pid=os.getpid())
                    time.sleep(.25)
                detail=read_detail(secret,ident)
                from mvcentr_contact_plan import optout
                blocked=optout(detail)
                save_profile(profiles,cipher,fingerprint,ident,detail,secret,reject_key_leak,optout=blocked)
                # Opt-outs are monotonic; never overwrite current passwords,
                # manual role changes, or source identity based on email.
                if blocked:
                    from apply_server_contacts import apply_optout
                    apply_optout(frappe,ACCOUNT,str(ident))
                return detail
            report=collect(folder/'contacts.sqlite',output,account=ACCOUNT,key=key,
                requests_per_second=3.0,fetch=fetch,stop_requested=lambda:(folder/'STOP').exists())
            write_status(output,status=report['status'],worker_pid=os.getpid(),
                error_code=report.get('error_code'),verified_links=report['verified_total'],
                captured_profiles=profiles.execute('SELECT COUNT(*) FROM profiles').fetchone()[0])
            return {'status':report['status'],'verified_links':report['verified_total']}
    finally:frappe.destroy();key=None


def launch(fingerprint,key):
    _,folder=read_selection(ACCOUNT,fingerprint)
    output=folder/'individual';private(output)
    if (folder/'STOP').exists() or (output/'STOP').exists():raise ApplyError('paused')
    with lock(output):pass
    fd=os.open(safe_file(output/'worker.log'),os.O_WRONLY|os.O_CREAT|os.O_APPEND|os.O_NOFOLLOW,0o600)
    with os.fdopen(fd,'ab',buffering=0) as log:
        child=subprocess.Popen([sys.executable,'-B',str(Path(__file__).resolve()),'--run',
            '--selection',fingerprint],stdin=subprocess.PIPE,stdout=log,stderr=log,
            start_new_session=True,close_fds=True)
        try:
            child.stdin.write(json.dumps({'key':key}).encode());child.stdin.close()
        except BaseException:
            child.terminate();child.wait(timeout=5);raise ApplyError('worker_start_failed') from None
    return {'status':'starting','account':ACCOUNT,'site':SITE,'worker_pid':child.pid,'key_saved':False}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--selection',required=True)
    group=parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--start',action='store_true');group.add_argument('--run',action='store_true')
    args=parser.parse_args();key=None;output=None;owns_lock=False
    try:
        verify_release();_,folder=read_selection(ACCOUNT,args.selection)
        output=folder/'individual';private(output)
        # Import only key validation, without a secret in arguments/env/files.
        api=BENCH/'sites'/SITE/'private/avo-api-archive'/('release-'+API_RELEASE)
        os.environ['AVO_SERVER_ARCHIVE_ACCOUNT']=ACCOUNT
        sys.path.insert(0,str(api));from server_archive_job import read_key
        key=read_key(sys.stdin.buffer)
        if args.start:result=launch(args.selection,key)
        else:
            with lock(output):
                owns_lock=True
                write_status(output,status='initializing',worker_pid=os.getpid())
                with open(os.devnull,'w') as quiet,redirect_stdout(quiet),redirect_stderr(quiet):
                    result=run(args.selection,key)
    except BaseException as error:
        result={'status':'stopped','account':ACCOUNT,'site':SITE,'error_code':type(error).__name__}
        if args.run and output is not None and owns_lock:
            write_status(output,**result,worker_pid=os.getpid())
    finally:key=None
    print(json.dumps(result))
    return 0 if result['status'] in ('starting','completed') else 2 if result['status']=='cancelled' else 1


if __name__=='__main__':raise SystemExit(main())

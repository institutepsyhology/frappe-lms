"""Apply completed MV/IOMP contact captures. MVC is deliberately not a target.

No AVO key, HTTP call or credential output. Existing source workers are untouched.
"""
import argparse
from collections import Counter
from contextlib import closing,contextmanager,redirect_stdout
from datetime import datetime,timezone
import hashlib
import json
import os
import re
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import time

from mvcentr_contact_plan import plan,email,EMAIL,matches,PlanError

SITES={'mastervision':'my-lk.mastervision.su','iomp':'my-lk.iomp.ru'}
RESERVE=2*1024**3
RELEASE_FILES=frozenset(('apply_server_contacts.py','server_contact_reader.py','mvcentr_contact_plan.py','server_archive_sink.py'))


class ApplyError(Exception):pass
class Paused(Exception):pass


def destination(account):
    if type(account) is not str or account not in SITES:raise ApplyError('wrong_account')
    return SITES[account]


def verify_release():
    folder=Path(__file__).resolve().parent
    if not re.fullmatch('release-[a-f0-9]{40}',folder.name):raise ApplyError('invalid_release')
    try:
        manifest=json.loads(safe_file(folder/'manifest.json').read_text())
        if set(manifest)!={'revision','files'} or manifest['revision']!=folder.name[8:] or set(manifest['files'])!=RELEASE_FILES:
            raise ApplyError('invalid_release')
        for name,digest in manifest['files'].items():
            if hashlib.sha256(safe_file(folder/name).read_bytes()).hexdigest()!=digest:raise ApplyError('invalid_release')
    except (OSError,ValueError,TypeError):raise ApplyError('invalid_release') from None
    return manifest['revision']


def stamp():return datetime.now(timezone.utc).isoformat()


def private(path):
    if path.is_symlink():raise ApplyError('unsafe_path')
    path.mkdir(mode=0o700,exist_ok=True)
    if path.stat().st_uid!=os.getuid():raise ApplyError('unsafe_path')
    os.chmod(path,0o700)


def safe_file(path):
    if path.is_symlink() or path.exists() and (not path.is_file() or path.stat().st_nlink!=1):
        raise ApplyError('unsafe_path')
    return path


@contextmanager
def lock(base):
    import fcntl
    fd=os.open(safe_file(base/'worker.lock'),os.O_RDWR|os.O_CREAT|os.O_NOFOLLOW,0o600)
    try:
        try:fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:raise ApplyError('already_running') from None
        yield
    finally:os.close(fd)


def open_state(base,account,snapshot):
    path=safe_file(base/'state.sqlite')
    fd=os.open(path,os.O_RDWR|os.O_CREAT|os.O_NOFOLLOW,0o600);os.close(fd)
    db=sqlite3.connect(path);db.execute('PRAGMA synchronous=FULL')
    db.executescript('''CREATE TABLE IF NOT EXISTS metadata(key TEXT PRIMARY KEY,value TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS decisions(source_id TEXT PRIMARY KEY,status TEXT NOT NULL,reason TEXT,at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY,source_id TEXT,status TEXT,reason TEXT,at TEXT);''')
    expected={'account':account,'site':destination(account),'snapshot':snapshot}
    actual=dict(db.execute('SELECT key,value FROM metadata'))
    if actual and actual!=expected:db.close();raise ApplyError('state_identity_mismatch')
    if not actual:
        with db:db.executemany('INSERT INTO metadata VALUES (?,?)',expected.items())
    return db


def record(db,ident,status,reason=None):
    with db:
        db.execute('INSERT INTO decisions VALUES (?,?,?,?) ON CONFLICT(source_id) DO UPDATE SET status=excluded.status,reason=excluded.reason,at=excluded.at',
            (ident,status,reason,stamp()))
        db.execute('INSERT INTO events VALUES(NULL,?,?,?,?)',(ident,status,reason,stamp()))


def progress(base,db,status,account,**extra):
    value={'site':destination(account),'account':account,'status':status,'worker_pid':os.getpid(),
        'counts':dict(db.execute('SELECT status,COUNT(*) FROM decisions GROUP BY status')),
        'updated_at':stamp(),**extra}
    path=safe_file(base/'progress.json');tmp=safe_file(base/'progress.tmp')
    fd=os.open(tmp,os.O_WRONLY|os.O_CREAT|os.O_TRUNC|os.O_NOFOLLOW,0o600)
    with os.fdopen(fd,'w') as stream:json.dump(value,stream,sort_keys=True);stream.flush();os.fsync(stream.fileno())
    os.replace(tmp,path)
    return value


def target_map(frappe,account):
    result={}
    for kind in ('User','Contact'):
        fields=['name','custom_avo_contact_id','custom_no_marketing_email']+(['user'] if kind=='Contact' else [])
        for row in frappe.get_all(kind,filters={'custom_avo_account':account},fields=fields,limit_page_length=0):
            ident=str(row.custom_avo_contact_id or '')
            if not ident:continue
            value={'kind':kind,'name':row.name,'blocked':bool(row.custom_no_marketing_email),'user':row.get('user')}
            if ident in result:
                previous=result[ident]
                if kind!='Contact' or previous['kind']!='User' or value['user']!=previous['name']:
                    raise ApplyError('ambiguous_source_identity')
                previous['blocked']=previous['blocked'] and value['blocked']
            else:result[ident]=value
    return result


def insert_one(frappe,decision,account):
    if frappe.local.site!=destination(account) or frappe.session.user!='Administrator':raise ApplyError('wrong_operator')
    data=decision['data']
    if data.get('custom_avo_account')!=account:raise ApplyError('source_identity_mismatch')
    ident=data['custom_avo_contact_id']
    frappe.db.begin()
    try:
        if any(frappe.db.exists(kind,{'custom_avo_account':account,'custom_avo_contact_id':ident}) for kind in ('User','Contact')):
            raise ApplyError('source_identity_already_exists')
        if decision['action']=='create_user':
            if frappe.db.exists('User',data['email']):raise ApplyError('email_already_exists')
            from lms.lms.avo_user_import import _insert_imported_user
            from lms.lms.support_credentials import store_new_user_password
            saved=frappe.get_doc({'doctype':'User',**data,'user_type':'Website User','send_welcome_email':0})
            saved.flags.ignore_password_policy=True
            _insert_imported_user(saved)
            store_new_user_password(saved.name,data['new_password'])
            if decision['source_banned']:frappe.db.set_value('User',saved.name,'enabled',0,update_modified=False)
            saved=frappe.get_doc('User',saved.name)
            if saved.user_type!='Website User' or saved.send_welcome_email or bool(saved.enabled)==bool(decision['source_banned']):
                raise ApplyError('new_user_readback_mismatch')
            if not frappe.db.sql("SELECT 1 FROM __Auth WHERE doctype='User' AND name=%s AND fieldname='lms_support_password' AND encrypted=1",(saved.name,)):
                raise ApplyError('support_copy_missing')
            kind='User'
        elif decision['action']=='create_contact':
            saved=frappe.get_doc(data)
            saved.insert(set_name='avo-'+account+'-contact-'+ident,ignore_permissions=True,
                ignore_mandatory=not bool(data['first_name']))
            saved=frappe.get_doc('Contact',saved.name);kind='Contact'
        else:raise ApplyError('invalid_action')
        if not matches(saved,data):raise ApplyError('contact_readback_mismatch')
        frappe.db.commit()
        return {'kind':kind,'name':saved.name,'blocked':bool(data['custom_no_marketing_email']),'user':None}
    except BaseException:frappe.db.rollback();raise


def wait_ready(*,pending,free,stopped,waiting,pause=time.sleep):
    while True:
        if stopped():raise Paused()
        if free()<RESERVE:waiting('waiting_for_space');pause(2);continue
        if pending()>=100:waiting('waiting_for_queue');pause(1);continue
        return


def insert_ready(frappe,decision,account,*,pending,free,stopped,waiting,pause=time.sleep):
    for attempt in range(10):
        wait_ready(pending=pending,free=free,stopped=stopped,waiting=waiting,pause=pause)
        try:return insert_one(frappe,decision,account)
        except Exception as error:
            if type(error).__name__!='QueueOverloaded':raise
            if attempt==9:raise ApplyError('queue_retry_limit') from None
            waiting('waiting_for_queue')
            for _ in range(min(60,2**(attempt+2))):
                if stopped():raise Paused()
                pause(0.5)
    raise ApplyError('queue_retry_limit')


def apply_optout(frappe,account,ident):
    from lms.lms.avo_marketing import apply_source_optouts
    frappe.db.begin()
    try:
        apply_source_optouts(account,[ident])
        for kind in ('User','Contact'):
            if frappe.db.sql('SELECT 1 FROM `tab'+kind+'` WHERE custom_avo_account=%s AND custom_avo_contact_id=%s AND coalesce(custom_no_marketing_email,0)<>1 LIMIT 1',(account,ident)):
                raise ApplyError('optout_readback_mismatch')
        frappe.db.commit()
    except BaseException:frappe.db.rollback();raise


def run(frappe,account,*,limit=20,retry_issues=False):
    site=destination(account)
    if frappe.local.site!=site or frappe.session.user!='Administrator':raise ApplyError('wrong_operator')
    from cryptography.fernet import Fernet
    from server_contact_reader import iter_contacts
    from frappe.utils.background_jobs import get_queue
    if not frappe.conf.encryption_key:raise ApplyError('existing_site_key_required')
    cipher=Fernet(frappe.conf.encryption_key.encode())
    job=Path(frappe.get_site_path('private','avo-api-archive','job-20261116'))
    base=Path(frappe.get_site_path('private','apply-avo-contacts'));private(base)
    with lock(base):
        frequencies=Counter();source_count=0
        # Full validation before the first production change. Only IDs/counts,
        # never passwords or row bodies, are retained beyond a source page.
        for row in iter_contacts(job,cipher,account):
            source_count+=1
            try:address=email(row)
            except PlanError:continue
            if EMAIL.fullmatch(address):frequencies[address]+=1
        with closing(sqlite3.connect((job/'snapshot.sqlite').resolve().as_uri()+'?mode=ro',uri=True)) as source:
            snapshot=dict(source.execute('SELECT key,value FROM metadata'))['snapshot']
        with closing(open_state(base,account,snapshot)) as state:
            identities=target_map(frappe,account)
            taken={str(x[0]).strip().lower() for x in frappe.db.sql('''SELECT email FROM tabUser
                UNION SELECT email_id FROM tabContact
                UNION SELECT email_id FROM `tabContact Email` WHERE parenttype='Contact' ''') if x[0]}
            done={ident for ident,status in state.execute('SELECT source_id,status FROM decisions')
                if not retry_issues or status not in ('deferred','failed')}
            queue=get_queue('default');failures=0;created=0;handled=0
            stopped=lambda:(base/'STOP').exists()
            update=lambda status:progress(base,state,status,account,source_count=source_count)
            update('applying')
            for row in iter_contacts(job,cipher,account):
                if stopped():return update('paused')
                ident=row['id_contact']
                if ident in done:continue
                try:
                    current=identities.get(ident)
                    decision=plan(row,account=account,existing_kind=current['kind'] if current else None,
                        email_frequency=frequencies.get(email(row),0) if not current else 0,
                        email_taken=email(row) in taken if not current else False)
                    action=decision['action'];reason=None
                    if action=='existing':
                        if decision['optout'] and not current['blocked']:
                            wait_ready(pending=lambda:queue.count,free=lambda:shutil.disk_usage(base).free,stopped=stopped,waiting=update)
                            apply_optout(frappe,account,ident);current['blocked']=True;status='existing_optout_set'
                        else:status='existing_preserved'
                    elif action=='deferred':status='deferred';reason=decision['reason']
                    else:
                        identities[ident]=insert_ready(frappe,decision,account,pending=lambda:queue.count,
                            free=lambda:shutil.disk_usage(base).free,stopped=stopped,waiting=update)
                        status='created_user' if action=='create_user' else 'created_contact'
                        if action=='create_user':taken.add(decision['data']['email'])
                        created+=1
                    record(state,ident,status,reason);failures=0
                except Paused:return update('paused')
                except Exception as error:
                    frappe.db.rollback()
                    reason=error.args[0] if isinstance(error,(ApplyError,PlanError)) else type(error).__name__
                    if reason=='queue_retry_limit':return progress(base,state,'stopped',account,error_code=reason,source_count=source_count)
                    record(state,ident,'failed',reason);failures+=1
                    if failures>=10:return progress(base,state,'stopped',account,error_code='ten_consecutive_failures',source_count=source_count)
                handled+=1
                if handled%20==0:update('applying')
                if limit and created>=limit:return update('batch_complete')
                # IOMP yields more time to MV and the single native default worker.
                time.sleep(0.15 if account=='mastervision' else 0.6)
            return update('completed_with_issues' if state.execute("SELECT 1 FROM decisions WHERE status IN ('failed','deferred') LIMIT 1").fetchone() else 'completed')


def launch(account):
    base=Path('/home/frappe/frappe-bench/sites')/destination(account)/'private/apply-avo-contacts';private(base)
    if (base/'STOP').exists():raise ApplyError('paused')
    # Reject an already running writer; the child also owns worker.lock itself.
    with lock(base):pass
    log=safe_file(base/'worker.log')
    fd=os.open(log,os.O_WRONLY|os.O_CREAT|os.O_APPEND|os.O_NOFOLLOW,0o600)
    with os.fdopen(fd,'ab',buffering=0) as stream:
        child=subprocess.Popen([sys.executable,'-B',str(Path(__file__).resolve()),'--account',account,'--apply','--limit','0'],
            stdin=subprocess.DEVNULL,stdout=stream,stderr=stream,start_new_session=True,close_fds=True)
    return {'status':'starting','account':account,'site':destination(account),'worker_pid':child.pid}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--account',required=True,choices=tuple(SITES))
    parser.add_argument('--apply',action='store_true');parser.add_argument('--start',action='store_true')
    parser.add_argument('--limit',type=int,default=20);parser.add_argument('--retry-issues',action='store_true')
    args=parser.parse_args()
    if args.apply==args.start or args.limit<0:raise SystemExit('explicit_action_required')
    frappe=None
    try:
        verify_release()
        if args.start:result=launch(args.account)
        else:
            import frappe
            frappe.init(site=destination(args.account));frappe.connect();frappe.set_user('Administrator')
            # Native import errors may contain source values. Never print them.
            with open(os.devnull,'w') as quiet,redirect_stdout(quiet):
                result=run(frappe,args.account,limit=args.limit,retry_issues=args.retry_issues)
    except Exception as error:
        result={'status':'stopped','account':args.account,'site':destination(args.account),
            'error_code':error.args[0] if isinstance(error,ApplyError) else type(error).__name__}
    finally:
        if frappe is not None:frappe.destroy()
    print(json.dumps(result))
    return 1 if result['status']=='stopped' else 0


if __name__=='__main__':raise SystemExit(main())

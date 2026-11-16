"""Trusted resumable MVC writer. No source key, account email or password in logs."""
import argparse
from collections import Counter
from contextlib import closing,contextmanager
from datetime import datetime,timezone
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import time

from mvcentr_archive_reader import iter_contacts,SITE,ACCOUNT
from mvcentr_contact_plan import plan,email,EMAIL,matches,PlanError

SNAPSHOT='fcd7f93e6efe4ce88f2f79f242a6116f'
BASE=Path('/home/frappe/frappe-bench/sites')/SITE/'private'/'apply-avo-contacts'


class ApplyError(Exception):pass


def stamp():return datetime.now(timezone.utc).isoformat()


def private(path):
    path=Path(path)
    if path.is_symlink():raise ApplyError('unsafe_path')
    path.mkdir(mode=0o700,exist_ok=True)
    if path.stat().st_uid!=os.getuid():raise ApplyError('unsafe_path')
    os.chmod(path,0o700)
    return path


@contextmanager
def worker_lock():
    import fcntl
    path=BASE/'worker.lock'
    if path.is_symlink():raise ApplyError('unsafe_path')
    fd=os.open(path,os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW,0o600)
    try:
        try:fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:raise ApplyError('already_running') from None
        yield
    finally:os.close(fd)


def policy():
    path=BASE/'policy.json'
    if path.is_symlink():raise ApplyError('unsafe_path')
    value=json.loads(path.read_text())
    if (type(value) is not dict or set(value)!={'account','excluded_ids','protected_ids'} or value['account']!=ACCOUNT
            or any(type(value[k]) is not list for k in ('excluded_ids','protected_ids'))
            or any(type(x) is not int or x<1 for k in ('excluded_ids','protected_ids') for x in value[k])):
        raise ApplyError('invalid_policy')
    return {k:{str(x) for x in value[k]} for k in ('excluded_ids','protected_ids')}


def state_database():
    path=BASE/'state.sqlite'
    if path.is_symlink():raise ApplyError('unsafe_path')
    fd=os.open(path,os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW,0o600);os.close(fd)
    db=sqlite3.connect(path);db.execute('PRAGMA synchronous=FULL')
    db.executescript('''CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY,value TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS decisions(source_id TEXT PRIMARY KEY,status TEXT NOT NULL,reason TEXT,at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY,source_id TEXT,status TEXT,reason TEXT,at TEXT);''')
    expected={'account':ACCOUNT,'site':SITE,'snapshot':SNAPSHOT}
    current=dict(db.execute('SELECT key,value FROM metadata'))
    if current and current!=expected:raise ApplyError('state_identity_mismatch')
    if not current:
        with db:db.executemany('INSERT INTO metadata VALUES (?,?)',expected.items())
    return db


def record(db,ident,status,reason=None):
    with db:
        db.execute('INSERT INTO decisions VALUES (?,?,?,?) ON CONFLICT(source_id) DO UPDATE SET status=excluded.status,reason=excluded.reason,at=excluded.at',
                   (ident,status,reason,stamp()))
        db.execute('INSERT INTO events VALUES (NULL,?,?,?,?)',(ident,status,reason,stamp()))


def progress(db,status,*,failures=0,error=None):
    value={'site':SITE,'account':ACCOUNT,'snapshot':SNAPSHOT,'status':status,'worker_pid':os.getpid(),
        'counts':dict(db.execute('SELECT status,COUNT(*) FROM decisions GROUP BY status')),
        'consecutive_failures':failures,'error_code':error,'updated_at':stamp()}
    path=BASE/'progress.json';temp=BASE/'progress.json.tmp'
    for candidate in (path,temp):
        if candidate.is_symlink():raise ApplyError('unsafe_path')
    fd=os.open(temp,os.O_WRONLY|os.O_CREAT|os.O_TRUNC|os.O_NOFOLLOW,0o600)
    with os.fdopen(fd,'w') as stream:json.dump(value,stream,sort_keys=True);stream.flush();os.fsync(stream.fileno())
    os.replace(temp,path)
    return value


def target_map(frappe):
    result={}
    for kind in ('User','Contact'):
        fields=['name','custom_avo_contact_id','custom_no_marketing_email']+(['user'] if kind=='Contact' else [])
        rows=frappe.get_all(kind,filters={'custom_avo_account':ACCOUNT},fields=fields,limit_page_length=0)
        for row in rows:
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


def insert_one(frappe,decision):
    data=decision['data']
    frappe.db.begin()
    try:
        if decision['action']=='create_user':
            from lms.lms.avo_user_import import import_user
            import_user(data)
            if decision['source_banned']:
                frappe.db.set_value('User',data['email'],'enabled',0,update_modified=False)
            saved=frappe.get_doc('User',data['email'])
            if not matches(saved,data) or bool(saved.enabled)==bool(decision['source_banned']):
                raise ApplyError('new_user_readback_mismatch')
            if not frappe.db.sql("SELECT 1 FROM __Auth WHERE doctype='User' AND name=%s AND fieldname='lms_support_password' AND encrypted=1",(saved.name,)):
                raise ApplyError('support_copy_missing')
            kind='User'
        else:
            saved=frappe.get_doc(data)
            saved.insert(set_name='avo-mv-centr-contact-'+data['custom_avo_contact_id'],
                ignore_permissions=True,ignore_mandatory=not bool(data['first_name']))
            saved=frappe.get_doc('Contact',saved.name)
            if not matches(saved,data):raise ApplyError('new_contact_readback_mismatch')
            kind='Contact'
        frappe.db.commit()
        return {'kind':kind,'name':saved.name,'blocked':bool(data['custom_no_marketing_email']),'user':None}
    except BaseException:
        frappe.db.rollback()
        raise


def block_one(frappe,ident):
    from lms.lms.avo_marketing import apply_source_optouts
    frappe.db.begin()
    try:
        apply_source_optouts(ACCOUNT,[ident])
        for kind in ('User','Contact'):
            if frappe.db.sql('SELECT 1 FROM `tab'+kind+'` WHERE custom_avo_account=%s AND custom_avo_contact_id=%s AND coalesce(custom_no_marketing_email,0)<>1 LIMIT 1',(ACCOUNT,ident)):
                raise ApplyError('optout_readback_mismatch')
        frappe.db.commit()
    except BaseException:frappe.db.rollback();raise


def run(frappe,*,limit=0,retry_issues=False):
    if frappe.local.site!=SITE or frappe.session.user!='Administrator':raise ApplyError('wrong_site_or_operator')
    from cryptography.fernet import Fernet
    if not frappe.conf.encryption_key:raise ApplyError('existing_site_key_required')
    cipher=Fernet(frappe.conf.encryption_key.encode())
    archive=Path(frappe.get_site_path('private','avo-ingest','archive.sqlite'))
    private(BASE)
    rules=policy()
    with worker_lock(),closing(state_database()) as state:
        progress(state,'verifying_source')
        frequencies=Counter()
        # Mandatory full verified pass before the first production write.
        for _,row in iter_contacts(archive,cipher,SNAPSHOT):
            if row['id_contact'] in rules['excluded_ids']:continue
            try:address=email(row)
            except PlanError:continue
            if EMAIL.fullmatch(address):frequencies[address]+=1
        identities=target_map(frappe)
        # A User insertion can reuse a native Contact by email. Preserve those
        # existing people too, including manually entered/unmapped Contacts.
        taken={str(x[0]).strip().lower() for x in frappe.db.sql('''SELECT email FROM tabUser
            UNION SELECT email_id FROM tabContact
            UNION SELECT email_id FROM `tabContact Email` WHERE parenttype='Contact' ''') if x[0]}
        done={ident for ident,status in state.execute('SELECT source_id,status FROM decisions')
              if not retry_issues or status not in ('deferred','failed')}
        failures=0;created=0;handled=0
        progress(state,'applying')
        for _,row in iter_contacts(archive,cipher,SNAPSHOT):
            ident=row['id_contact']
            if (BASE/'STOP').exists():return progress(state,'paused')
            if ident in done:continue
            try:
                current=identities.get(ident)
                guarded=ident in rules['excluded_ids'] or ident in rules['protected_ids']
                result=plan(row,existing_kind=current['kind'] if current else None,
                    excluded=ident in rules['excluded_ids'],protected=ident in rules['protected_ids'],
                    email_frequency=frequencies.get(email(row),0) if not current and not guarded else 0,
                    email_taken=email(row) in taken if not current and not guarded else False)
                action=result['action'];reason=None
                if action in ('excluded','protected'):
                    status=action
                elif action=='existing':
                    if result['optout'] and not current['blocked']:
                        block_one(frappe,ident);current['blocked']=True;status='existing_optout_set'
                    else:status='existing_preserved'
                elif action=='deferred':
                    status='deferred';reason=result['reason']
                else:
                    # Reconcile the exact source identity immediately before insert.
                    if any(frappe.db.exists(kind,{'custom_avo_account':ACCOUNT,'custom_avo_contact_id':ident}) for kind in ('User','Contact')):
                        identities=target_map(frappe);current=identities[ident]
                        status='existing_preserved'
                    else:
                        identities[ident]=insert_one(frappe,result)
                        status='created_user' if action=='create_user' else 'created_contact'
                        if action=='create_user':taken.add(result['data']['email'])
                        created+=1
                record(state,ident,status,reason);failures=0
            except Exception as error:
                frappe.db.rollback()
                reason=error.args[0] if isinstance(error,(ApplyError,PlanError)) else type(error).__name__
                record(state,ident,'failed',reason);failures+=1
                if failures>=10:return progress(state,'stopped',failures=failures,error='ten_consecutive_failures')
                time.sleep(0.2)
            handled+=1
            if handled%100==0 or created and created%10==0:progress(state,'applying',failures=failures)
            if limit and created>=limit:return progress(state,'batch_complete',failures=failures)
        return progress(state,'completed_with_issues' if state.execute("SELECT 1 FROM decisions WHERE status IN ('failed','deferred') LIMIT 1").fetchone() else 'completed')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--limit',type=int,default=20)
    parser.add_argument('--apply',action='store_true')
    parser.add_argument('--retry-issues',action='store_true')
    args=parser.parse_args()
    if not args.apply or args.limit<0:raise SystemExit('explicit_apply_required')
    import frappe
    try:
        frappe.init(site=SITE);frappe.connect();frappe.set_user('Administrator')
        result=run(frappe,limit=args.limit,retry_issues=args.retry_issues)
        print(json.dumps(result))
        return 1 if result['status']=='stopped' else 0
    except Exception as error:
        # Frappe exceptions may contain emails/passwords; never print str(error).
        result={'status':'stopped','error_type':type(error).__name__,'site':SITE}
        if not (isinstance(error,ApplyError) and error.args==('already_running',)):
            try:
                if (BASE/'state.sqlite').is_file():
                    with closing(state_database()) as state:result=progress(state,'stopped',error=type(error).__name__)
            except Exception:pass
        print(json.dumps(result))
        return 1
    finally:frappe.destroy()


if __name__=='__main__':raise SystemExit(main())

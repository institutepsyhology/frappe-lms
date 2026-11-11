"""Archive matching AVO passwords for already imported MV-Centr users.

Secrets stay in memory and transit only over the authenticated HTTPS channel.
The journal contains source IDs and statuses, not email addresses or passwords.
"""
import argparse
import importlib.util
import json
import msvcrt
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parent))
import import_mvcentr_users as source

JOURNAL=source.JOURNAL.with_name('mvcentr-support-password-events.jsonl')


def event(ident,status):
    with JOURNAL.open('a',encoding='utf-8') as f:
        f.write(json.dumps({'account':'mv-centr','contact_id':ident,'status':status})+'\n')


def users_for_ids(ids,headers):
    filters=[['custom_avo_account','=','mv-centr'],['custom_avo_contact_id','in',[str(i) for i in ids]]]
    query=urllib.parse.urlencode({'filters':json.dumps(filters),'fields':json.dumps(['name','custom_avo_contact_id']),
                                  'limit':str(len(ids)+1)})
    req=urllib.request.Request(source.SITE+'/api/v2/document/User?'+query,headers=headers)
    with source.DIRECT_OPENER.open(req,timeout=40) as response:rows=json.load(response).get('data')
    if not isinstance(rows,list):raise ValueError('invalid_users_response')
    result={}
    for row in rows:
        ident=row.get('custom_avo_contact_id');name=row.get('name')
        if not isinstance(ident,str) or not ident.isdigit() or not isinstance(name,str) or int(ident) not in ids or int(ident) in result:
            raise ValueError('ambiguous_users_response')
        result[int(ident)]=name
    return result


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--apply',action='store_true')
    parser.add_argument('--limit',type=int,default=1)
    parser.add_argument('--interval',type=float,default=1.5)
    args=parser.parse_args()
    if args.limit<1 or not 0.5<=args.interval<=60:parser.error('invalid limit or interval')
    report=json.loads((source.ROOT/'exports/contacts-api-all-fields/report.json').read_text(encoding='utf-8'))
    if report.get('origin')!='https://mvcentr.autoweboffice.ru':raise ValueError('source_account_mismatch')
    done=set()
    if JOURNAL.exists():
        for line in JOURNAL.read_text(encoding='utf-8').splitlines():
            item=json.loads(line)
            if item.get('account')!='mv-centr' or type(item.get('contact_id')) is not int:raise ValueError('invalid_journal')
            if item.get('status')=='stored':done.add(item['contact_id'])
    spec=importlib.util.spec_from_file_location('h',source.ROOT/'frappe-mcp/headers.py')
    helper=importlib.util.module_from_spec(spec);spec.loader.exec_module(helper)
    headers=helper.authenticated_headers('my-lk.mv-centr.ru')
    counts={'checked':0,'stored':0,'mismatch':0,'not_yet_imported':0}
    consecutive=0
    def process(batch):
        nonlocal consecutive
        mapping=users_for_ids([i for i,_ in batch],headers)
        for ident,record in batch:
            if ident in done:continue
            name=mapping.get(ident)
            if not name:counts['not_yet_imported']+=1;continue
            password=(record.get('credentials') or {}).get('password')
            if not isinstance(password,str) or not password:
                event(ident,'missing_password');consecutive+=1
            elif args.apply:
                payload={'name':name,'source_id':str(ident),'password':password}
                req=urllib.request.Request(source.SITE+'/api/method/lms.lms.support_credentials.import_verified',
                    data=json.dumps(payload).encode('utf-8'),headers={**headers,'Content-Type':'application/json'},method='POST')
                try:
                    with source.DIRECT_OPENER.open(req,timeout=40) as response:result=json.load(response).get('message')
                    if not isinstance(result,dict) or type(result.get('stored')) is not bool:raise ValueError('invalid_response')
                    counts['checked']+=1
                    if result['stored']:
                        event(ident,'stored');counts['stored']+=1;consecutive=0
                        if counts['stored']%25==0:print(json.dumps({'progress_created':counts['stored']}),flush=True)
                    else:event(ident,'mismatch');counts['mismatch']+=1;consecutive+=1
                except urllib.error.HTTPError as exc:
                    event(ident,'http_error');counts['stopped']='http_'+str(exc.code);return False
                except Exception:
                    event(ident,'write_uncertain');counts['stopped']='write_uncertain';return False
                time.sleep(args.interval)
            else:counts['checked']+=1;consecutive=0
            if consecutive>=10:counts['stopped']='consecutive_issues';return False
            if counts['checked']>=args.limit:return False
        return True
    batch=[]
    for ident,record in source.load():
        if ident in source.EXCLUDED_CONTACTS or ident in done:continue
        batch.append((ident,record))
        if len(batch)>=100:
            if not process(batch):break
            batch=[]
    else:
        if batch:process(batch)
    print(json.dumps(counts))


if __name__=='__main__':
    path=JOURNAL.with_name('mvcentr-support-password-import.lock')
    with path.open('a+b') as lock:
        lock.seek(0,2)
        if lock.tell()==0:lock.write(b'0');lock.flush()
        lock.seek(0)
        try:msvcrt.locking(lock.fileno(),msvcrt.LK_NBLCK,1)
        except OSError:raise SystemExit('another_import_is_running')
        try:main()
        finally:lock.seek(0);msvcrt.locking(lock.fileno(),msvcrt.LK_UNLCK,1)

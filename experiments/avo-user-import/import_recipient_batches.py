"""Import the selected MV-Centr recipients in small recoverable batches."""
import argparse
import collections
import importlib.util
import json
import msvcrt

import import_mvcentr_users as source
from import_recipient_selection import merge_complaint
import recipient_batch as batch


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--apply',action='store_true')
    parser.add_argument('--limit',type=int,default=1)
    args=parser.parse_args()
    if args.limit<1: parser.error('invalid limit')
    private=source.JOURNAL.parent
    status=json.loads((private/'mvcentr-user-import-status.json').read_text(encoding='utf-8-sig'))
    marker=json.loads((private/'mvcentr-user-import-paused.json').read_text(encoding='utf-8-sig'))
    if status.get('status')!='paused' or marker.get('status')!='paused' or status.get('worker_pid')!=marker.get('worker_pid'):
        raise RuntimeError('general_import_not_paused')
    previous=private/'mvcentr-priority-contact-status.json'
    if previous.exists() and json.loads(previous.read_text(encoding='utf-8-sig')).get('status') in ('running','paused_for_deployment'):
        raise RuntimeError('another_priority_import_running')
    selected=json.loads((private/'nov11-recipients-user-ids.json').read_text(encoding='utf-8'))
    complaints=json.loads((private/'nov11-recipients-complaint-ids.json').read_text(encoding='utf-8'))
    overrides=json.loads((private/'nov11-recipients-current-overrides.json').read_text(encoding='utf-8'))
    if any(not isinstance(a,list) or any(type(i) is not int or i<1 for i in a) for a in (selected,complaints)) or not isinstance(overrides,dict):
        raise ValueError('invalid_selection')
    selected=set(selected);complaints=set(complaints)
    lock_path=private/'nov11-recipients-import.lock'
    with lock_path.open('a+b') as lock:
        lock.seek(0,2)
        if lock.tell()==0:lock.write(b'0');lock.flush()
        lock.seek(0)
        try:msvcrt.locking(lock.fileno(),msvcrt.LK_NBLCK,1)
        except OSError as exc:raise RuntimeError('recipient_import_running') from exc
        try: run(args,selected,complaints,overrides)
        finally:
            lock.seek(0);msvcrt.locking(lock.fileno(),msvcrt.LK_UNLCK,1)


def run(args, selected, complaints, overrides):
    if args.apply: batch.recover_pending()
    done=set(); conflicts=set(); unresolved=set()
    if source.JOURNAL.exists():
        with source.JOURNAL.open(encoding='utf-8') as f:
            for line in f:
                event=json.loads(line);ident=event.get('contact_id');status=event.get('status')
                if event.get('account')!='mv-centr' or type(ident) is not int:raise ValueError('invalid_journal')
                if status in ('unique_conflict','validation_conflict'):conflicts.add(ident)
                elif status in ('created_verified','present_verified'):done.add(ident);conflicts.discard(ident)
                if status in ('write_outcome_unknown','readback_mismatch'):unresolved.add(ident)
                elif status in ('created_verified','resolved_not_created'):unresolved.discard(ident)
    if unresolved:
        print(json.dumps({'stopped':'unresolved_write','unresolved_write_outcomes':len(unresolved)}));return
    frequencies=collections.Counter(source.email_of(record) for _,record in source.load())
    headers={}
    if args.apply:
        spec=importlib.util.spec_from_file_location('frappe_headers',source.ROOT/'frappe-mcp/headers.py')
        helper=importlib.util.module_from_spec(spec);spec.loader.exec_module(helper)
        headers=helper.authenticated_headers('my-lk.mv-centr.ru')
    counters=collections.Counter(created=0,consecutive_issues=0)
    records=[]
    for ident,record in source.load():
        if ident not in selected or ident in source.EXCLUDED_CONTACTS:continue
        if ident in done:
            counters['existing_skipped']+=1;counters['consecutive_issues']=0;continue
        data=merge_complaint(source.payload(ident,record),ident,complaints,overrides)
        issue=None
        if ident in conflicts:issue='known_conflict_skipped'
        elif not data:issue='missing_email_or_password'
        elif frequencies[data['email']]!=1:issue='duplicate_source_email'
        if issue:
            if records:
                if args.apply and not batch.transfer(records,headers,counters):break
                records=[]
            counters[issue]+=1;counters['consecutive_issues']+=1
            if args.apply and issue!='known_conflict_skipped':source.log_event(ident,issue)
            if counters['consecutive_issues']>=10:
                counters['stopped']='consecutive_issues';break
            continue
        if not args.apply:
            counters['eligible']+=1;continue
        data.pop('user_type',None);data.pop('send_welcome_email',None)
        records.append((ident,data))
        if len(records)>=min(10,args.limit-counters['created']):
            if not batch.transfer(records,headers,counters):break
            records=[]
            if counters['created']>=args.limit:break
    else:
        if records and args.apply:batch.transfer(records,headers,counters)
    print(json.dumps(dict(counters),sort_keys=True))


if __name__=='__main__':main()

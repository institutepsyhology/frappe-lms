"""Import the unambiguous part of the November 11 MV-Centr recipient list."""
import argparse
import json
import msvcrt
import sys
from pathlib import Path

import import_mvcentr_users as source


def merge_complaint(data, ident, complaints, overrides=None):
    if data and ident in complaints:
        data['custom_no_marketing_email']=1
    if data and overrides and str(ident) in overrides:
        values=overrides[str(ident)]
        allowed={'first_name','middle_name','last_name','mobile_no'}
        if not isinstance(values,dict) or set(values)-allowed or any(not isinstance(v,str) or not v or len(v)>140 for v in values.values()):
            raise ValueError('invalid_current_data')
        data.update(values)
    return data


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--limit', type=int, default=1)
    args=parser.parse_args()
    private=source.JOURNAL.parent
    status=json.loads((private/'mvcentr-user-import-status.json').read_text(encoding='utf-8-sig'))
    marker=json.loads((private/'mvcentr-user-import-paused.json').read_text(encoding='utf-8-sig'))
    if status.get('status')!='paused' or marker.get('status')!='paused' or status.get('worker_pid')!=marker.get('worker_pid'):
        raise RuntimeError('general_import_not_paused')
    previous=private/'mvcentr-priority-contact-status.json'
    if previous.exists() and json.loads(previous.read_text(encoding='utf-8-sig')).get('status') in ('running','paused_for_deployment'):
        raise RuntimeError('another_priority_import_running')
    selected=private/'nov11-recipients-user-ids.json'
    complaints=json.loads((private/'nov11-recipients-complaint-ids.json').read_text(encoding='utf-8'))
    if not isinstance(complaints,list) or any(type(i) is not int or i<1 for i in complaints):
        raise ValueError('invalid_complaint_ids')
    complaints=set(complaints)
    overrides=json.loads((private/'nov11-recipients-current-overrides.json').read_text(encoding='utf-8'))
    if not isinstance(overrides,dict) or any(not str(k).isdigit() for k in overrides):
        raise ValueError('invalid_current_data')
    original=source.payload
    def payload(ident,record):
        return merge_complaint(original(ident,record),ident,complaints,overrides)
    source.payload=payload
    source.AUTO_RECONCILE_RECIPIENTS=True
    lock_path=private/'nov11-recipients-import.lock'
    with lock_path.open('a+b') as lock:
        lock.seek(0,2)
        if lock.tell()==0:lock.write(b'0');lock.flush()
        lock.seek(0)
        try:msvcrt.locking(lock.fileno(),msvcrt.LK_NBLCK,1)
        except OSError as exc:raise RuntimeError('recipient_import_running') from exc
        try:
            sys.argv=['recipient-import','--ids-file',str(selected),'--limit',str(args.limit),'--interval','0.1']
            if args.apply:sys.argv.append('--apply')
            source.main()
        finally:
            lock.seek(0);msvcrt.locking(lock.fileno(),msvcrt.LK_UNLCK,1)


if __name__=='__main__':main()

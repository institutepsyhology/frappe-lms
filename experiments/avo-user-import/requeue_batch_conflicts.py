"""Retry selected conflicts logged by the batch version with a transient-error bug.

Run only while the selected-recipient worker is stopped. Only IDs are written.
Already verified contacts and contacts outside the selected source are skipped.
"""
import json
import os
from datetime import datetime,timezone

import import_mvcentr_users as source

CUTOFF='2026-11-11T22:05:00+00:00'

def candidates(events,selected):
    after=datetime.fromisoformat(CUTOFF)
    last={}
    for event in events:
        ident=event.get('contact_id');date=event.get('at')
        if event.get('account')!='mv-centr' or type(ident) is not int or ident not in selected or not isinstance(date,str):continue
        if datetime.fromisoformat(date) < after:continue
        status=event.get('status')
        if status in ('validation_conflict','retry_validation_conflict','created_verified','present_verified'):
            last[ident]=status
    return sorted(i for i,status in last.items() if status=='validation_conflict')

def main():
    private=source.JOURNAL.parent
    raw=json.loads((private/'nov11-recipients-user-ids.json').read_text(encoding='utf-8'))
    if not isinstance(raw,list) or any(type(i) is not int or i<1 for i in raw):raise ValueError('invalid_selection')
    with source.JOURNAL.open(encoding='utf-8') as f: ids=candidates((json.loads(line) for line in f),set(raw))
    stamp=datetime.now(timezone.utc).isoformat()
    with source.JOURNAL.open('a',encoding='utf-8') as out:
        for ident in ids:
            out.write(json.dumps({'at':stamp,'contact_id':ident,'account':'mv-centr','status':'retry_validation_conflict'})+'\n')
        out.flush();os.fsync(out.fileno())
    print(json.dumps({'requeued':len(ids)}))

if __name__=='__main__':main()

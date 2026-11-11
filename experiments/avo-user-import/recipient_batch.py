"""Bounded MV-Centr batches with durable intent and per-contact reconciliation.

The checkpoint contains only AVO IDs; credentials remain in memory. A request
may commit any prefix even on timeout, so nothing is retried before every ID
has been matched against both the source ID and email on the destination.
"""
import json
import os
import time
import urllib.parse
import urllib.request

import import_mvcentr_users as source
import recipient_recovery as recovery

FIELDS = ['name','email','first_name','middle_name','last_name','mobile_no',
          'custom_avo_contact_id','custom_avo_account','custom_avo_telegram_id',
          'custom_avo_telegram_username','custom_avo_vk_id','custom_avo_vk_username',
          'custom_no_marketing_email']
PENDING = source.JOURNAL.with_name('mvcentr-recipient-batch-pending.json')


def write_pending(ids):
    if PENDING.exists() or not ids or len(ids) > 10 or len(set(ids)) != len(ids):
        raise ValueError('invalid_batch_checkpoint')
    temp = PENDING.with_suffix('.tmp')
    with temp.open('x', encoding='utf-8') as out:
        json.dump({'account':'mv-centr', 'ids':ids}, out)
        out.flush()
        os.fsync(out.fileno())
    os.replace(temp, PENDING)


def read_pending():
    data = json.loads(PENDING.read_text(encoding='utf-8'))
    ids = data.get('ids')
    if data.get('account') != 'mv-centr' or not isinstance(ids,list) or not 1 <= len(ids) <= 10 or any(type(i) is not int or i < 1 for i in ids) or len(set(ids)) != len(ids):
        raise ValueError('invalid_batch_checkpoint')
    return ids


def recover_pending(inspect=recovery.inspect, wait=time.sleep):
    """Resolve checkpoint after a crash. Never retry an ambiguous identity."""
    if not PENDING.exists(): return
    for ident in read_pending():
        for attempt in range(10):
            try:
                result = inspect(ident)
                if result in ('present', 'absent', 'conflict'): break
            except (OSError, ValueError):
                pass
            if attempt < 9: wait(min(5 * (attempt + 1), 30))
        else: raise RuntimeError('batch_recovery_unavailable')
        if result == 'conflict': raise RuntimeError('batch_identity_conflict')
        source.log_event(ident, 'created_verified' if result == 'present' else 'resolved_not_created')
    PENDING.unlink()


def _lookup(filters, headers, limit):
    q=urllib.parse.urlencode({'filters':json.dumps(filters),'fields':json.dumps(FIELDS),'limit':limit})
    req=urllib.request.Request(source.SITE + '/api/v2/document/User?' + q, headers=headers)
    with source.DIRECT_OPENER.open(req, timeout=40) as response:
        rows=json.load(response).get('data')
    if not isinstance(rows,list): raise ValueError('invalid_response')
    return rows


def reconcile(records, headers):
    ids=[str(i) for i,_ in records]
    emails=[d['email'] for _,d in records]
    by_id=_lookup([['custom_avo_account','=','mv-centr'],['custom_avo_contact_id','in',ids]],headers,2*len(ids)+1)
    by_email=_lookup([['email','in',emails]],headers,2*len(ids)+1)
    return {i:recovery.classify([r for r in by_id if r.get('custom_avo_contact_id')==str(i)],
             [r for r in by_email if r.get('email')==d['email']],d) for i,d in records}


def post(records, headers):
    payload={'records':[d for _,d in records]}
    request=urllib.request.Request(source.SITE+'/api/method/lms.lms.avo_user_import.import_users_batch',
        data=json.dumps(payload).encode('utf-8'), headers={**headers,'Content-Type':'application/json'},method='POST')
    with source.DIRECT_OPENER.open(request,timeout=60) as response:
        result=json.load(response).get('message')
    if not isinstance(result,dict) or type(result.get('processed')) is not int or type(result.get('failed')) is not bool:
        raise ValueError('invalid_response')
    if not 0 <= result['processed'] <= len(records) or (not result['failed'] and result['processed'] != len(records)):
        raise ValueError('invalid_response')
    if result['failed'] and (result['processed'] >= len(records) or result.get('reason') not in ('rejected','unexpected')):
        raise ValueError('invalid_response')
    return result


def transfer(records, headers, counters, wait=time.sleep):
    """Return False on a hard stop; every retry is preceded by read-back."""
    remaining=list(records)
    failures=0
    while remaining:
        write_pending([i for i,_ in remaining])
        try: response=post(remaining,headers)
        except Exception: response=None
        results=None
        for attempt in range(10):
            try:
                results=reconcile(remaining,headers)
                break
            except (OSError,ValueError):
                if attempt<9: wait(min(5*(attempt+1),30))
        if results is None:
            counters['stopped']='batch_readback_unavailable'
            return False
        if any(result=='conflict' for result in results.values()):
            counters['stopped']='batch_identity_conflict'
            return False
        present=[i for i,_ in remaining if results[i]=='present']
        for ident in present: source.log_event(ident,'created_verified')
        before=counters['created']
        counters['created']+=len(present)
        if counters['created']//25 > before//25:
            print(json.dumps({'progress_created':counters['created']}),flush=True)
        if present: counters['consecutive_issues']=0
        rejected=None
        if response and response['failed'] and response['reason']=='rejected':
            ident=remaining[response['processed']][0]
            if results[ident]=='absent': rejected=ident
        absent=[item for item in remaining if results[item[0]]=='absent' and item[0]!=rejected]
        if rejected is not None:
            source.log_event(rejected,'validation_conflict')
            counters['validation_conflict_skipped']+=1
            counters['consecutive_issues']+=1
        PENDING.unlink()
        if counters['consecutive_issues']>=10:
            counters['stopped']='consecutive_issues'
            return False
        if response and response['failed'] and response['reason']=='unexpected':
            counters['stopped']='batch_server_error'
            return False
        if absent and rejected is None:
            failures+=1
            if failures>=10:
                counters['stopped']='batch_retry_limit'
                return False
            wait(min(5*failures,30))
        else: failures=0
        remaining=absent
    return True

"""Preserve selected same-email AVO identities as separate Frappe Contacts.

No login account is created or linked. The ID list and journal are private.
"""
import argparse
import importlib.util
import json
import sqlite3
import sys
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import import_mvcentr_users as source

PRIVATE = source.JOURNAL.parent
JOURNAL = PRIVATE / 'mvcentr-priority-duplicate-contact-events.jsonl'
SELECTION = PRIVATE / 'mvcentr-nov10-priority-duplicate-ids.json'


def make_payload(ident, record):
    contact = record.get('contact') or {}
    email = source.email_of(record)
    if not source.EMAIL.fullmatch(email):
        raise ValueError('invalid_source_email')
    first = str(contact.get('name') or '').strip()
    last = str(contact.get('last_name') or '').strip()
    if not first and not last:
        first = 'Контакт АВО ' + str(ident)
    result = {'doctype':'Contact', 'first_name':first, 'last_name':last,
              'middle_name':str(contact.get('middle_name') or '').strip(),
              'custom_avo_contact_id':str(ident), 'custom_avo_account':'mv-centr',
              'custom_avo_telegram_id':str(contact.get('telegram_user_id') or ''),
              'custom_avo_telegram_username':str(contact.get('telegram_user') or ''),
              'custom_avo_vk_id':str(contact.get('vk_user_id') or ''),
              'custom_avo_vk_username':str(contact.get('vk_user') or ''),
              'custom_avo_source_email':str(contact.get('email') or ''),
              'custom_no_marketing_email':source.marketing_optout(record),
              'email_ids':[{'email_id':email,'is_primary':1}]}
    phone = str(contact.get('phone_number') or '').strip()
    if phone:
        result['phone_nos'] = [{'phone':phone,'is_primary_mobile_no':1}]
    return result


def event(ident, status):
    with JOURNAL.open('a',encoding='utf-8') as f:
        f.write(json.dumps({'contact_id':ident,'account':'mv-centr','status':status})+'\n')


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--apply',action='store_true')
    parser.add_argument('--limit',type=int,default=1)
    args=parser.parse_args()
    ids=json.loads(SELECTION.read_text(encoding='utf-8'))
    if not isinstance(ids,list) or len(ids)!=len(set(ids)) or any(type(i) is not int or i<1 for i in ids) or args.limit<1:
        raise ValueError('invalid_selection')
    done=set();unknown=set()
    if JOURNAL.exists():
        for line in JOURNAL.read_text(encoding='utf-8').splitlines():
            x=json.loads(line)
            if x.get('account')!='mv-centr' or type(x.get('contact_id')) is not int:raise ValueError('invalid_journal')
            if x['status']=='created_verified':done.add(x['contact_id']);unknown.discard(x['contact_id'])
            elif x['status']=='write_outcome_unknown':unknown.add(x['contact_id'])
            elif x['status']=='resolved_not_created':unknown.discard(x['contact_id'])
    if unknown:print(json.dumps({'stopped':'unresolved_write','count':len(unknown)}));return
    headers={}
    if args.apply:
        spec=importlib.util.spec_from_file_location('headers',source.ROOT/'frappe-mcp/headers.py')
        helper=importlib.util.module_from_spec(spec);spec.loader.exec_module(helper)
        headers=helper.authenticated_headers('my-lk.mv-centr.ru')
    db=sqlite3.connect((source.ROOT/'exports/contacts-api-all-fields/contacts.sqlite').resolve().as_uri()+'?mode=ro',uri=True)
    counts={'eligible':0,'created':0,'already_recorded':0}
    for ident in ids:
        if ident in source.EXCLUDED_CONTACTS:continue
        row=db.execute('select record_json from contacts where id=?',(ident,)).fetchone()
        if not row:raise ValueError('source_contact_missing')
        data=make_payload(ident,json.loads(row[0]));counts['eligible']+=1
        if not args.apply:continue
        if ident in done:counts['already_recorded']+=1;continue
        req=urllib.request.Request(source.SITE+'/api/v2/document/Contact',
            data=json.dumps(data,ensure_ascii=False).encode('utf-8'),
            headers={**headers,'Content-Type':'application/json'},method='POST')
        try:
            with source.DIRECT_OPENER.open(req,timeout=30) as response:saved=json.load(response).get('data') or {}
            keys=['first_name','last_name','middle_name','custom_avo_contact_id','custom_avo_account',
                  'custom_avo_telegram_id','custom_avo_telegram_username','custom_avo_vk_id',
                  'custom_avo_vk_username','custom_avo_source_email','custom_no_marketing_email']
            ok=all(str(saved.get(k) or '')==str(data.get(k) or '') for k in keys)
            ok=ok and saved.get('email_id')==data['email_ids'][0]['email_id']
            if data.get('phone_nos'):ok=ok and saved.get('mobile_no')==data['phone_nos'][0]['phone']
            if not ok:event(ident,'write_outcome_unknown');counts['stopped']='readback_mismatch';break
            event(ident,'created_verified');counts['created']+=1
        except urllib.error.HTTPError as exc:
            event(ident,'write_outcome_unknown' if exc.code>=500 or 300<=exc.code<400 else 'rejected')
            counts['stopped']='http_'+str(exc.code);break
        except Exception:
            event(ident,'write_outcome_unknown');counts['stopped']='write_outcome_unknown';break
        if counts['created']>=args.limit:break
    print(json.dumps(counts))


if __name__=='__main__':main()

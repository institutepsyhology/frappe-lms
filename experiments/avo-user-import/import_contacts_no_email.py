"""Import MV-Centr AVO contacts without usable email as Contact records.

No synthetic email or login is created. Passwords and source details are never
printed or written to the progress journal. Defaults to read-only preflight.
"""
import argparse
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE))
import import_mvcentr_users as source

JOURNAL=source.JOURNAL.with_name('mvcentr-noemail-contact-events.jsonl')


def payload(ident,record):
    c=record.get('contact') or {}
    email=source.email_of(record)
    if source.EMAIL.fullmatch(email):return None
    first=str(c.get('name') or '').strip()
    last=str(c.get('last_name') or '').strip()
    middle=str(c.get('middle_name') or '').strip()
    if not first and not last:first='Контакт АВО '+str(ident)
    data={'doctype':'Contact','first_name':first,'last_name':last,'middle_name':middle,
          'custom_avo_contact_id':str(ident),'custom_avo_account':'mv-centr',
          'custom_avo_telegram_id':str(c.get('telegram_user_id') or ''),
          'custom_avo_telegram_username':str(c.get('telegram_user') or ''),
          'custom_avo_vk_id':str(c.get('vk_user_id') or ''),
          'custom_avo_vk_username':str(c.get('vk_user') or ''),
          'custom_avo_source_email':str(c.get('email') or '')}
    phone=str(c.get('phone_number') or '').strip()
    if phone:data['phone_nos']=[{'phone':phone,'is_primary_mobile_no':1}]
    return data


def event(ident,status):
    if type(ident)!=int or ident<1 or not re.fullmatch(r'[a-z_]+',status):raise ValueError('invalid_event')
    with JOURNAL.open('a',encoding='utf-8') as f:
        f.write(json.dumps({'contact_id':ident,'account':'mv-centr','status':status})+'\n')


def main():
    import importlib.util
    parser=argparse.ArgumentParser()
    parser.add_argument('--apply',action='store_true')
    parser.add_argument('--limit',type=int,default=1)
    parser.add_argument('--contact',type=int)
    args=parser.parse_args()
    if args.limit<1 or (args.contact is not None and args.contact<1):parser.error('invalid limit or ID')
    done=set();unknown=set()
    if args.apply and JOURNAL.exists():
        with JOURNAL.open(encoding='utf-8') as f:
            for line in f:
                x=json.loads(line);ident=x.get('contact_id')
                if x.get('account')!='mv-centr' or type(ident)!=int:raise ValueError('invalid_journal')
                if x.get('status')=='created_verified':done.add(ident);unknown.discard(ident)
                elif x.get('status')=='write_outcome_unknown':unknown.add(ident)
                elif x.get('status')=='resolved_not_created':unknown.discard(ident)
    if unknown:
        print(json.dumps({'stopped':'unresolved_write','count':len(unknown)}));return
    headers={}
    if args.apply:
        spec=importlib.util.spec_from_file_location('h',source.ROOT/'frappe-mcp/headers.py')
        helper=importlib.util.module_from_spec(spec);spec.loader.exec_module(helper)
        headers=helper.authenticated_headers('my-lk.mv-centr.ru')
    counts={'eligible':0,'created':0,'already_recorded':0}
    for ident,record in source.load():
        if ident in source.EXCLUDED_CONTACTS or (args.contact is not None and ident!=args.contact):continue
        data=payload(ident,record)
        if data is None:continue
        counts['eligible']+=1
        if not args.apply:continue
        if ident in done:counts['already_recorded']+=1;continue
        req=urllib.request.Request(source.SITE+'/api/v2/document/Contact',
             data=json.dumps(data,ensure_ascii=False).encode('utf-8'),
             headers={**headers,'Content-Type':'application/json'},method='POST')
        try:
            with source.DIRECT_OPENER.open(req,timeout=30) as response:
                saved=json.load(response).get('data') or {}
            keys=['first_name','middle_name','last_name','custom_avo_contact_id','custom_avo_account',
                  'custom_avo_telegram_id','custom_avo_telegram_username','custom_avo_vk_id',
                  'custom_avo_vk_username','custom_avo_source_email']
            same=all(str(saved.get(k) or '')==str(data.get(k) or '') for k in keys)
            if data.get('phone_nos'):
                same=same and saved.get('mobile_no')==data['phone_nos'][0]['phone']
            if not same or saved.get('email_id'):
                event(ident,'write_outcome_unknown');counts['stopped']='readback_mismatch';break
            event(ident,'created_verified');counts['created']+=1
        except urllib.error.HTTPError as exc:
            event(ident,'write_outcome_unknown' if exc.code>=500 or 300<=exc.code<400 else 'rejected')
            counts['stopped']='http_'+str(exc.code);break
        except Exception:
            event(ident,'write_outcome_unknown');counts['stopped']='write_outcome_unknown';break
        if counts['created']>=args.limit:break
        time.sleep(1)
    print(json.dumps(counts))


if __name__=='__main__':main()

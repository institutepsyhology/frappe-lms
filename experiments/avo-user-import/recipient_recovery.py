"""Resolve an uncertain MV-Centr user creation without exposing contact data."""
import importlib.util
import json
import sqlite3
import urllib.parse
import urllib.request

import import_mvcentr_users as source
from import_recipient_selection import merge_complaint


def classify(by_id, by_email, expected):
    if not by_id and not by_email:return 'absent'
    if len(by_id)!=1 or len(by_email)!=1:return 'conflict'
    a,b=by_id[0],by_email[0]
    if a.get('name')!=b.get('name') or a.get('custom_avo_account')!='mv-centr' or a.get('custom_avo_contact_id')!=expected['custom_avo_contact_id']:
        return 'conflict'
    # A newer opt-out must never be undone or treated as an error.
    saved=dict(a)
    if saved.get('custom_no_marketing_email') and not expected.get('custom_no_marketing_email'):
        saved['custom_no_marketing_email']=0
    return 'present' if source.saved_matches(saved,expected) else 'conflict'


def unresolved_id():
    pending=set()
    if source.JOURNAL.exists():
        with source.JOURNAL.open(encoding='utf-8') as f:
            for line in f:
                e=json.loads(line)
                if e.get('account')!='mv-centr' or type(e.get('contact_id')) is not int:raise ValueError('invalid_journal')
                if e.get('status') in ('write_outcome_unknown','readback_mismatch'):pending.add(e['contact_id'])
                elif e.get('status') in ('created_verified','resolved_not_created'):pending.discard(e['contact_id'])
    if len(pending)!=1:raise ValueError('uncertain_record_count')
    return pending.pop()


def inspect(ident):
    private=source.JOURNAL.parent
    selected=json.loads((private/'nov11-recipients-user-ids.json').read_text(encoding='utf-8'))
    if ident not in selected:raise ValueError('outside_selection')
    db=sqlite3.connect((private/'contacts.sqlite').resolve().as_uri()+'?mode=ro',uri=True)
    try:row=db.execute('select record_json from contacts where id=?',(ident,)).fetchone()
    finally:db.close()
    if not row:raise ValueError('missing_source')
    complaints=set(json.loads((private/'nov11-recipients-complaint-ids.json').read_text(encoding='utf-8')))
    overrides=json.loads((private/'nov11-recipients-current-overrides.json').read_text(encoding='utf-8'))
    expected=merge_complaint(source.payload(ident,json.loads(row[0])),ident,complaints,overrides)
    if not expected:raise ValueError('invalid_source')
    spec=importlib.util.spec_from_file_location('h',source.ROOT/'frappe-mcp/headers.py')
    h=importlib.util.module_from_spec(spec);spec.loader.exec_module(h)
    headers=h.authenticated_headers('my-lk.mv-centr.ru')
    fields=['name','email','first_name','middle_name','last_name','mobile_no','custom_avo_contact_id','custom_avo_account',
            'custom_avo_telegram_id','custom_avo_telegram_username','custom_avo_vk_id','custom_avo_vk_username','custom_no_marketing_email']
    def lookup(filters):
        query=urllib.parse.urlencode({'filters':json.dumps(filters),'fields':json.dumps(fields),'limit':3})
        request=urllib.request.Request(source.SITE+'/api/v2/document/User?'+query,headers=headers)
        with source.DIRECT_OPENER.open(request,timeout=30) as response:data=json.load(response).get('data')
        if not isinstance(data,list):raise ValueError('invalid_response')
        return data
    by_id=lookup([['custom_avo_account','=','mv-centr'],['custom_avo_contact_id','=',str(ident)]])
    by_email=lookup([['email','=',expected['email']]])
    return classify(by_id,by_email,expected)

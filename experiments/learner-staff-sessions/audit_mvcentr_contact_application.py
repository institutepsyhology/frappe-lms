"""Server-only, read-only coverage audit; outputs aggregates, never contact values."""
from collections import Counter
import json
from pathlib import Path
import re
import sys

from mvcentr_archive_reader import iter_contacts

SITE='my-lk.mv-centr.ru'
SNAPSHOT='fcd7f93e6efe4ce88f2f79f242a6116f'
EMAIL=re.compile(r'[^@\s]+@[^@\s]+\.[^@\s]+\Z')


def main():
    import frappe
    from cryptography.fernet import Fernet
    policy=json.loads(sys.stdin.buffer.read(65537))
    if (not isinstance(policy,dict) or set(policy)!={'account','excluded_ids','protected_ids'}
            or policy['account']!='mv-centr'
            or any(type(x) is not int or x<1 for key in ('excluded_ids','protected_ids') for x in policy[key])):
        raise ValueError('invalid_private_policy')
    excluded={str(x) for x in policy['excluded_ids']}
    protected={str(x) for x in policy['protected_ids']}
    frappe.init(site=SITE);frappe.connect()
    try:
        cipher=Fernet(frappe.conf.encryption_key.encode())
        archive=Path(frappe.get_site_path('private','avo-ingest','archive.sqlite'))
        users={str(x[0]) for x in frappe.db.sql("SELECT custom_avo_contact_id FROM tabUser WHERE custom_avo_account=%s AND custom_avo_contact_id<>''",('mv-centr',))}
        contacts={str(x[0]) for x in frappe.db.sql("SELECT custom_avo_contact_id FROM tabContact WHERE custom_avo_account=%s AND custom_avo_contact_id<>''",('mv-centr',))}
        target_emails={str(x[0]).strip().lower() for x in frappe.db.sql("SELECT email FROM tabUser") if x[0]}
        frequencies=Counter();source_ids=set();missing={};counts=Counter()
        for _,row in iter_contacts(archive,cipher,SNAPSHOT):
            ident=row['id_contact'];source_ids.add(ident)
            email=row.get('email')
            if not isinstance(email,str):email=''
            email=email.strip().lower()
            if EMAIL.fullmatch(email):frequencies[email]+=1
            counts['source_records']+=1
            if ident in excluded:counts['excluded']+=1;continue
            if ident in protected:counts['protected']+=1;continue
            if ident in users or ident in contacts:
                counts['existing']+=1
            else:
                missing[ident]=(email,isinstance(row.get('password'),str) and bool(row['password']))
                counts['missing']+=1
            if row.get('not_to_write')=='1' or row.get('spam_clicked')=='1':counts['source_optout']+=1
        for email,has_password in missing.values():
            if not EMAIL.fullmatch(email):counts['missing_without_valid_email']+=1
            elif frequencies[email]>1 or email in target_emails:counts['missing_shared_email']+=1
            elif not has_password:counts['missing_without_password']+=1
            else:counts['missing_unique_email_users']+=1
        counts['target_only_source_ids']=len((users|contacts)-source_ids)
        cross_linked=frappe.db.sql("""SELECT COUNT(*) FROM tabContact c JOIN tabUser u ON u.name=c.user
            WHERE c.custom_avo_account=%s AND (coalesce(u.custom_avo_account,'')<>c.custom_avo_account
            OR coalesce(u.custom_avo_contact_id,'')<>c.custom_avo_contact_id)""",('mv-centr',))[0][0]
        print(json.dumps({'site':SITE,'snapshot':SNAPSHOT,'mode':'read_only','source_complete_verified':True,
            'counts':dict(counts),'existing_cross_identity_contact_links':cross_linked,'database_changed':False}))
    finally:frappe.destroy()


if __name__=='__main__':
    try:main()
    except Exception as error:
        print(json.dumps({'mode':'read_only','status':'stopped','error_type':type(error).__name__}))
        raise SystemExit(1)

"""Linux-only synthetic server archive check. Never calls AVO or creates LMS users."""
import argparse
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import sys
import uuid


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--release',required=True)
    args=parser.parse_args()
    base=Path('/home/frappe/frappe-bench/sites/my-lk.mastervision.su/private/avo-api-archive')
    release=base/('release-'+args.release)
    sys.path.insert(0,str(release))
    import server_archive_job as job
    assert job.verify_release()==args.release
    job.bound_runtime()
    import legacy_api_snapshot as source
    import collect_personal_links_bulk as links
    from private_link_storage import unprotect_url
    from audit_legacy_links import SHOP_HOST
    folder=base/('.synthetic-check-'+uuid.uuid4().hex)
    folder.mkdir(mode=0o700)
    contacts=next(item for item in source.RESOURCES if item.name=='contacts')
    def fetch(key,resource,page,size,sort):
        body=json.dumps([{'id_contact':1},{'id_contact':2}]).encode() if page==0 else b'No items where found for model <b>contacts</b>'
        return source.Response(200,body)
    def detail(key,ident):
        return {'id_contact':ident,'link_personal_auth':'https://'+SHOP_HOST+
            '/personal/auth/secure-login?uid='+str(ident)+'&vc=SYNTHETIC_TOKEN_'+str(ident)}
    def child(source_db,output,**kwargs):
        return links.collect(source_db,output,fetch=detail,**kwargs)
    report=source.collect(folder,key='SYNTHETIC_KEY',account='mastervision',resources=(contacts,),
        fetch=fetch,collect_links=True,link_collector=child,requests_per_second=1,link_requests_per_second=1)
    assert report['status']=='completed_with_gaps' and report['links_status']=='completed'
    linkdir=folder/('links-'+report['snapshot'])
    with closing(sqlite3.connect(linkdir/'links.sqlite')) as db:
        rows=db.execute('SELECT source_id,url_encrypted FROM links').fetchall()
        assert len(rows)==2
        for ident,encrypted in rows:assert unprotect_url(ident,encrypted)==detail(None,ident)['link_personal_auth']
    with closing(sqlite3.connect(folder/'snapshot.sqlite')) as db:
        row=db.execute('SELECT resource,page,raw_encrypted FROM pages WHERE parse_code=?',('accepted',)).fetchone()
        decoded=source.unprotect_page(*row)
        assert json.loads(decoded['raw'])==[{'id_contact':1},{'id_contact':2}]
    print(json.dumps({'site':'my-lk.mastervision.su','synthetic_pipeline_verified':True,
        'encrypted_contacts':2,'encrypted_pages_verified':True,'avo_requests':0,'lms_users_created':0}))
    # Only the fixed synthetic files created by this invocation are removed.
    for name in ('links.sqlite','links.sqlite-wal','links.sqlite-shm','collector.lock','progress.json'):
        (linkdir/name).unlink(missing_ok=True)
    linkdir.rmdir()
    for name in ('snapshot.sqlite','snapshot.sqlite-journal','contacts.sqlite','collector.lock','progress.json'):
        (folder/name).unlink(missing_ok=True)
    folder.rmdir()


if __name__=='__main__':main()

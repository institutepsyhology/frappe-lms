#!/usr/bin/env python3
"""Identify file-metadata differences without reading any live site volume."""
import collections
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import tarfile
import tempfile

import compact_image as comp
from verify_candidate import TARGET,EXPECTED_CANDIDATE,stream_export


def main():
    if os.geteuid()!=0 or comp.run(['hostname']).decode().strip()!='spb-3-vm-t6fa':raise RuntimeError('unexpected_host')
    source,candidate=json.loads(comp.run(['docker','image','inspect',comp.SOURCE,TARGET]))
    live=json.loads(comp.run(['docker','inspect','company-lms-backend-1']))[0]
    if source['Id']!=comp.EXPECTED or live.get('Image')!=comp.EXPECTED or candidate['Id']!=EXPECTED_CANDIDATE:raise RuntimeError('unexpected_image')
    if source['Config']!=candidate['Config']:raise RuntimeError('configuration_mismatch')
    if comp.WORK.is_symlink() or comp.WORK.resolve()!=Path('/opt/company-lms/image-compaction'):raise RuntimeError('invalid_work_directory')
    old=None;new=None
    try:
        old=comp.create_container(comp.SOURCE,'codex-diagnose-source-'+os.urandom(6).hex())
        new=comp.create_container(TARGET,'codex-diagnose-candidate-'+os.urandom(6).hex())
        with tempfile.TemporaryDirectory(prefix='diagnose-',dir=comp.WORK) as temp:
            db=sqlite3.connect(Path(temp)/'index.sqlite');db.execute('create table files(name text primary key,metadata text not null,seen integer not null default 0)')
            try:
                print(json.dumps({'step':'indexing_source'}),flush=True)
                count=stream_export(old,lambda f:comp.index_archive(f,db))
                print(json.dumps({'step':'diagnosing_candidate','source_entries':count}),flush=True)
                differences=collections.Counter();examples=[];candidate_count=0
                def compare(stream):
                    nonlocal candidate_count
                    with tarfile.open(fileobj=stream,mode='r|*') as tar:
                        for member in tar:
                            candidate_count+=1;actual=json.loads(comp.describe(member,tar))
                            row=db.execute('select metadata,seen from files where name=?',(member.name,)).fetchone()
                            if not row: keys=['extra_path']
                            elif row[1]:keys=['duplicate_path']
                            else:
                                expected=json.loads(row[0]);keys=[k for k in expected if expected.get(k)!=actual.get(k)]
                                db.execute('update files set seen=1 where name=?',(member.name,))
                            if keys:
                                differences.update(keys)
                                if len(examples)<8:
                                    known={'etc/hostname','etc/hosts','etc/resolv.conf','.dockerenv','dev','proc','sys'}
                                    name=member.name.removeprefix('./')
                                    examples.append({'path':name if name in known else 'sha256:'+hashlib.sha256(name.encode()).hexdigest()[:16],'fields':keys})
                    differences['missing_path']=db.execute('select count(*) from files where seen=0').fetchone()[0]
                    return candidate_count
                stream_export(new,compare)
                print(json.dumps({'source_entries':count,'candidate_entries':candidate_count,
                                  'differences':dict(differences),'examples':examples}),flush=True)
            finally:db.close()
    finally:
        if new:comp.run(['docker','rm',new])
        if old:comp.run(['docker','rm',old])


if __name__=='__main__':
    try:main()
    except Exception as e:
        print(json.dumps({'ok':False,'reason':str(e) if str(e) in {'unexpected_host','unexpected_image','configuration_mismatch','invalid_work_directory','export_failed','duplicate_archive_path'} else type(e).__name__}),flush=True);raise SystemExit(1)

#!/usr/bin/env python3
"""Compare a specific already-created candidate with the current image.

Both archives come from fresh stopped containers with empty tmpfs mounts; no
production containers or volumes are exported. No running service is switched.
"""
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile

import compact_image as comp

TARGET='company-lms:flat-verified-20261105'
EXPECTED_CANDIDATE='sha256:b90574d3160c04f5d1597a85a30f23cbdeee017607d89729333237d3e6d13486'


def stream_export(cid,consume):
    proc=subprocess.Popen(['docker','export',cid],stdout=subprocess.PIPE,stderr=subprocess.PIPE)
    try:
        result=consume(proc.stdout)
        proc.stdout.close();err=proc.stderr.read();code=proc.wait(timeout=1800)
        if code:raise RuntimeError('export_failed')
        return result
    except BaseException:
        proc.kill();proc.wait();raise


def main():
    if os.geteuid()!=0 or comp.run(['hostname']).decode().strip()!='spb-3-vm-t6fa':raise RuntimeError('unexpected_host')
    images=json.loads(comp.run(['docker','image','inspect',comp.SOURCE,TARGET]));source,candidate=images
    live=json.loads(comp.run(['docker','inspect','company-lms-backend-1']))[0]
    if source['Id']!=comp.EXPECTED or live.get('Image')!=comp.EXPECTED or candidate['Id']!=EXPECTED_CANDIDATE:
        raise RuntimeError('unexpected_image')
    if source['Config']!=candidate['Config'] or source['Os']!=candidate['Os'] or source['Architecture']!=candidate['Architecture']:
        raise RuntimeError('configuration_mismatch')
    if len(candidate['RootFS']['Layers'])!=1:raise RuntimeError('unexpected_layer_count')
    comp.WORK.mkdir(mode=0o700,parents=True,exist_ok=True)
    if comp.WORK.is_symlink() or comp.WORK.resolve()!=Path('/opt/company-lms/image-compaction'):raise RuntimeError('invalid_work_directory')
    old=None;new=None
    try:
        old=comp.create_container(comp.SOURCE,'codex-verify-source-'+os.urandom(6).hex())
        new=comp.create_container(TARGET,'codex-verify-candidate-'+os.urandom(6).hex())
        with tempfile.TemporaryDirectory(prefix='verify-',dir=comp.WORK) as temp:
            db=sqlite3.connect(Path(temp)/'index.sqlite');db.execute('create table files(name text primary key,metadata text not null,seen integer not null default 0)')
            try:
                print(json.dumps({'step':'indexing_source'}),flush=True)
                count=stream_export(old,lambda f:comp.index_archive(f,db))
                print(json.dumps({'step':'comparing_candidate','source_entries':count}),flush=True)
                compared=stream_export(new,lambda f:comp.compare_archive(f,db))
                if count!=compared:raise RuntimeError('file_count_mismatch')
            finally:db.close()
        probe=['docker','run','--rm','--network','none']
        for dst in comp.VOLUMES:probe+=['--mount','type=tmpfs,destination='+dst]
        probe+=['--entrypoint','/home/frappe/frappe-bench/env/bin/python',TARGET,'-c',
                'import frappe, lms.lms.avo_import, lms.lms.avo_transform, lms.lms.avo_html_fragment; print("probe_ok")']
        if comp.run(probe,timeout=120).strip()!=b'probe_ok':raise RuntimeError('application_probe_failed')
        print(json.dumps({'ok':True,'source_image':source['Id'],'candidate_image':candidate['Id'],
             'layers':1,'configuration_identical':True,'filesystem_entries_compared':count,
             'filesystem_identical':True,'application_imports_ok':True}),flush=True)
    finally:
        if new:comp.run(['docker','rm',new])
        if old:comp.run(['docker','rm',old])


if __name__=='__main__':
    try:main()
    except Exception as e:
        allowed={'unexpected_host','unexpected_image','configuration_mismatch','unexpected_layer_count','invalid_work_directory','file_count_mismatch','application_probe_failed','export_failed','filesystem_mismatch','filesystem_missing_files','duplicate_archive_path'}
        print(json.dumps({'ok':False,'reason':str(e) if str(e) in allowed else type(e).__name__}),flush=True);sys.exit(1)

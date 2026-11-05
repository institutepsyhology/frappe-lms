#!/usr/bin/env python3
"""Build and verify a one-layer candidate from an image, never a live container.

This phase does not switch production. It exports only a fresh, stopped container
created from the image with tmpfs covering the two declared volume paths. A
one-layer OCI image is assembled with the original image Config and platform;
the candidate is accepted only after configuration and file-by-file comparison.
"""
import hashlib
import io
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import subprocess
import sys
import tarfile
import tempfile

EXPECTED='sha256:3f17259b3d8233c36db2d4abf812289b61c76cc5a139b96b10c6c24cf234ccae'
SOURCE='company-lms:avo-html-fragment-20261105'
TARGET='company-lms:flat-baseline-20261105'
WORK=Path('/opt/company-lms/image-compaction')
VOLUMES=('/home/frappe/frappe-bench/sites','/home/frappe/frappe-bench/logs')


def run(args, *, timeout=120, input_data=None):
    result=subprocess.run(args,input=input_data,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=timeout)
    if result.returncode:raise RuntimeError('command_failed_'+args[0])
    return result.stdout


def build_config(image,diff_id):
    if not re.fullmatch(r'sha256:[a-f0-9]{64}',diff_id):raise ValueError('invalid_diff_id')
    config={'architecture':image['Architecture'],'os':image['Os'],'config':image['Config'],
            'rootfs':{'type':'layers','diff_ids':[diff_id]},
            'history':[{'created_by':'compacted image from verified source'}]}
    for source,target in (('Variant','variant'),('OsVersion','os.version'),('OsFeatures','os.features')):
        if image.get(source):config[target]=image[source]
    if image.get('Created'):config['created']=image['Created']
    return config


def describe(member,stream):
    digest=''
    if member.isfile():
        data=stream.extractfile(member)
        if data is None:raise ValueError('missing_archive_data')
        h=hashlib.sha256()
        while True:
            chunk=data.read(1024*1024)
            if not chunk:break
            h.update(chunk)
        digest=h.hexdigest()
    # Docker creates these two virtual mount-point directories anew per container.
    # Preserve all metadata checks except their observed per-container mtimes.
    ephemeral=member.isdir() and member.name.removeprefix('./').rstrip('/') in ('dev/pts','dev/shm')
    meta={'name':member.name,'type':member.type.decode('latin1'),'mode':member.mode,
          'uid':member.uid,'gid':member.gid,'size':member.size,'mtime':None if ephemeral else member.mtime,
          'linkname':member.linkname,'devmajor':member.devmajor,'devminor':member.devminor,
          'pax':dict(sorted(member.pax_headers.items())),'sha256':digest}
    return json.dumps(meta,sort_keys=True,separators=(',',':'),ensure_ascii=True)


def file_manifest(fileobj):
    records={}
    with tarfile.open(fileobj=fileobj,mode='r|*') as stream:
        for member in stream:
            if member.name in records:raise ValueError('duplicate_archive_path')
            records[member.name]=describe(member,stream)
    return records


def digest_file(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda:f.read(4*1024*1024),b''):h.update(chunk)
    return h.hexdigest()


def create_container(image,name):
    args=['docker','create','--name',name,'--network','none']
    for dst in VOLUMES:args+=['--mount','type=tmpfs,destination='+dst]
    args+=['--entrypoint','/bin/true',image]
    cid=run(args).decode().strip()
    if not re.fullmatch(r'[a-f0-9]{64}',cid):raise RuntimeError('invalid_container_id')
    try:
        info=json.loads(run(['docker','inspect',cid]))[0]
        mounts=info.get('Mounts',[])
        if len(mounts)!=len(VOLUMES) or {(m.get('Type'),m.get('Destination')) for m in mounts}!={('tmpfs',p) for p in VOLUMES}:
            raise RuntimeError('unexpected_container_mounts')
    except BaseException:
        run(['docker','rm',cid]);raise
    return cid


def index_archive(source,db):
    count=0
    with tarfile.open(fileobj=source,mode='r|*') as stream:
        for member in stream:
            try:db.execute('insert into files(name,metadata) values (?,?)',(member.name,describe(member,stream)))
            except sqlite3.IntegrityError:raise ValueError('duplicate_archive_path') from None
            count+=1
    db.commit();return count


def compare_archive(source,db):
    count=0
    with tarfile.open(fileobj=source,mode='r|*') as stream:
        for member in stream:
            row=db.execute('select metadata,seen from files where name=?',(member.name,)).fetchone()
            if not row or row[1] or row[0]!=describe(member,stream):raise ValueError('filesystem_mismatch')
            db.execute('update files set seen=1 where name=?',(member.name,));count+=1
    if db.execute('select count(*) from files where seen=0').fetchone()[0]:raise ValueError('filesystem_missing_files')
    db.commit();return count


def blob(directory,data):
    digest=hashlib.sha256(data).hexdigest();(directory/digest).write_bytes(data)
    return {'digest':'sha256:'+digest,'size':len(data)}


def create_candidate(source,image,temp):
    if image['Id']!=EXPECTED or len(image['RootFS']['Layers'])!=499:raise RuntimeError('source_image_changed')
    live=json.loads(run(['docker','inspect','company-lms-backend-1']))[0]
    if live.get('Image')!=EXPECTED:raise RuntimeError('running_image_changed')
    existing=subprocess.run(['docker','image','inspect',TARGET],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    if existing.returncode==0:raise RuntimeError('candidate_tag_already_exists')
    config=image['Config']
    if set((config.get('Volumes') or {}).keys())!=set(VOLUMES):raise RuntimeError('unexpected_image_volumes')
    free=shutil.disk_usage(WORK).free
    if free < image['Size']*2+2*1024**3:raise RuntimeError('insufficient_disk_space')
    candidate=None;old=None
    try:
        old=create_container(source,'codex-flatten-source-'+os.urandom(6).hex())
        rootfs=temp/'rootfs.tar'
        run(['docker','export','--output',str(rootfs),old],timeout=1800)
        sha=digest_file(rootfs);size=rootfs.stat().st_size
        layout=temp/'oci';blobs=layout/'blobs'/'sha256';blobs.mkdir(parents=True)
        os.link(rootfs,blobs/sha)
        config_data=json.dumps(build_config(image,'sha256:'+sha),separators=(',',':'),ensure_ascii=True).encode()
        cd=blob(blobs,config_data);cd['mediaType']='application/vnd.oci.image.config.v1+json'
        md={'schemaVersion':2,'mediaType':'application/vnd.oci.image.manifest.v1+json','config':cd,
            'layers':[{'mediaType':'application/vnd.oci.image.layer.v1.tar','digest':'sha256:'+sha,'size':size}]}
        manifest=blob(blobs,json.dumps(md,separators=(',',':')).encode());manifest['mediaType']='application/vnd.oci.image.manifest.v1+json'
        manifest['annotations']={'org.opencontainers.image.ref.name':TARGET}
        (layout/'oci-layout').write_text('{"imageLayoutVersion":"1.0.0"}',encoding='ascii')
        (layout/'index.json').write_text(json.dumps({'schemaVersion':2,'manifests':[manifest]},separators=(',',':')),encoding='ascii')
        proc=subprocess.Popen(['docker','image','load'],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
        try:
            with tarfile.open(fileobj=proc.stdin,mode='w|') as out:
                for name in ('oci-layout','index.json','blobs'):out.add(layout/name,arcname=name,recursive=True)
            proc.stdin.close();stdout=proc.stdout.read();stderr=proc.stderr.read();code=proc.wait(timeout=1800)
        except BaseException:proc.kill();proc.wait();raise
        if code:raise RuntimeError('candidate_load_failed')
        candidate=json.loads(run(['docker','image','inspect',TARGET]))[0]
        if candidate['Config']!=config:raise RuntimeError('candidate_config_mismatch')
        if candidate['Os']!=image['Os'] or candidate['Architecture']!=image['Architecture'] or len(candidate['RootFS']['Layers'])!=1:
            raise RuntimeError('candidate_platform_or_layers_mismatch')
        other=create_container(TARGET,'codex-flatten-candidate-'+os.urandom(6).hex())
        try:
            db=sqlite3.connect(temp/'filesystem-index.sqlite');db.execute('create table files(name text primary key,metadata text not null,seen integer not null default 0)')
            with rootfs.open('rb') as f:before=index_archive(f,db)
            proc=subprocess.Popen(['docker','export',other],stdout=subprocess.PIPE,stderr=subprocess.PIPE)
            try:
                after=compare_archive(proc.stdout,db);proc.stdout.close();err=proc.stderr.read();code=proc.wait(timeout=1800)
            except BaseException:proc.kill();proc.wait();raise
            finally:db.close()
            if code or before!=after:raise RuntimeError('candidate_export_mismatch')
        finally:run(['docker','rm',other])
        probe=['docker','run','--rm','--network','none']
        for dst in VOLUMES:probe+=['--mount','type=tmpfs,destination='+dst]
        probe+=['--entrypoint','/home/frappe/frappe-bench/env/bin/python',TARGET,'-c',
                'import frappe, lms.lms.avo_import, lms.lms.avo_transform, lms.lms.avo_html_fragment; print("probe_ok")']
        if run(probe,timeout=120).strip()!=b'probe_ok':raise RuntimeError('candidate_probe_failed')
        return {'source_image':image['Id'],'candidate_image':candidate['Id'],'source_layers':499,'candidate_layers':1,
                'configuration_identical':True,'filesystem_entries_compared':before,'filesystem_identical':True,'application_imports_ok':True}
    finally:
        if old:run(['docker','rm',old])


def main():
    if os.geteuid()!=0:raise RuntimeError('root_required')
    if run(['hostname']).decode().strip()!='spb-3-vm-t6fa':raise RuntimeError('unexpected_host')
    WORK.mkdir(mode=0o700,parents=True,exist_ok=True)
    if WORK.is_symlink() or WORK.resolve()!=Path('/opt/company-lms/image-compaction'):raise RuntimeError('invalid_work_directory')
    image=json.loads(run(['docker','image','inspect',SOURCE]))[0]
    with tempfile.TemporaryDirectory(prefix='run-',dir=WORK) as directory:
        report=create_candidate(SOURCE,image,Path(directory))
    print(json.dumps(report,sort_keys=True))


if __name__=='__main__':
    try:main()
    except Exception as e:
        allowed={'root_required','unexpected_host','invalid_work_directory','source_image_changed','running_image_changed','candidate_tag_already_exists','unexpected_image_volumes','insufficient_disk_space','unexpected_container_mounts','candidate_load_failed','candidate_config_mismatch','candidate_platform_or_layers_mismatch','filesystem_mismatch','filesystem_missing_files','candidate_export_mismatch','candidate_probe_failed','duplicate_archive_path'}
        print(json.dumps({'ok':False,'reason':str(e) if str(e) in allowed else type(e).__name__}));sys.exit(1)

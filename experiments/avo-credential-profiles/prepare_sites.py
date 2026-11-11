"""Back up each site and prepare its encryption key, without printing secrets.

Run on the existing LMS host as root before activating the release. No old
backups or existing encryption keys are removed or replaced.
"""
import datetime
import gzip
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess

BASE=Path('/opt/company-lms')
SITES=('my-lk.mv-centr.ru','my-lk.iomp.ru','my-lk.mastervision.su')
CONTAINER='company-lms-backend-1'
BENCH='/home/frappe/frappe-bench'
EXPECTED='sha256:13d25c60100985c6042644cb83a5aa2e15275bbaa61cd5abc1b8dd82dac523fc'


def run(args):
    result=subprocess.run(args,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
    if result.returncode:raise RuntimeError('preparation_command_failed')
    return result.stdout


def copy_private(src,dst):
    if src.is_symlink() or not src.is_file() or src.stat().st_size==0:raise ValueError('invalid_backup_source')
    fd=os.open(dst,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
    with src.open('rb') as source,os.fdopen(fd,'wb') as target:
        shutil.copyfileobj(source,target,1024*1024);target.flush();os.fsync(target.fileno())
    if hashlib.sha256(src.read_bytes()).digest()!=hashlib.sha256(dst.read_bytes()).digest():
        raise RuntimeError('backup_copy_mismatch')


def main():
    if os.geteuid()!=0 or subprocess.check_output(['hostname'],text=True).strip()!='spb-3-vm-t6fa':
        raise RuntimeError('unexpected_host_or_user')
    actual=run(['docker','inspect','--format','{{.Image}}',CONTAINER]).strip()
    if actual!=EXPECTED:raise RuntimeError('unexpected_active_image')
    mounts=json.loads(run(['docker','volume','inspect','company-lms_sites']))
    sites_root=Path(mounts[0]['Mountpoint']).resolve(strict=True)
    info=(BASE/'backups').stat()
    if info.st_uid!=0 or info.st_mode & 0o077:raise RuntimeError('backup_root_not_private')
    stamp=datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    destination=BASE/'backups'/('contact-card-'+stamp);destination.mkdir(mode=0o700)
    results=[]
    for site in SITES:
        root=(sites_root/site).resolve(strict=True)
        if not root.is_relative_to(sites_root) or root.name!=site:raise ValueError('unsafe_site_path')
        staging=root/'private'/'backups'/('contact-card-'+stamp)
        container_staging=f'{BENCH}/sites/{site}/private/backups/contact-card-{stamp}'
        if staging.exists():raise ValueError('backup_path_exists')
        # bench backup calls delete_temp_backups even with a custom path.
        # Call the generator directly so no existing backup is removed.
        backup_code='''import frappe,sys\nfrom frappe.utils.backups import BackupGenerator\nfrappe.init(site=sys.argv[1]);frappe.connect();c=frappe.conf\ntry:\n b=BackupGenerator(c.db_name,c.db_user,c.db_password,db_socket=c.db_socket,db_host=c.db_host,db_port=c.db_port,db_type=c.db_type,backup_path=sys.argv[2],ignore_conf=True)\n b.get_backup(ignore_files=True,force=True)\nfinally: frappe.destroy()\n'''
        run(['docker','exec','-u','frappe','-w',f'{BENCH}/sites',CONTAINER,
             f'{BENCH}/env/bin/python','-c',backup_code,site,container_staging])
        dumps=list(staging.glob('*.sql.gz'))
        if len(dumps)!=1:raise RuntimeError('database_backup_missing')
        with gzip.open(dumps[0],'rb') as stream:
            prefix=stream.read(4096)
            if b'MariaDB dump' not in prefix and b'MySQL dump' not in prefix:raise RuntimeError('invalid_database_backup')
            while stream.read(1024*1024):pass
        target=destination/site;target.mkdir(mode=0o700)
        copy_private(dumps[0],target/'database.sql.gz')
        config=root/'site_config.json';copy_private(config,target/'site-config-before.json')
        code='''import frappe,sys\nfrom frappe.utils.password import get_encryption_key\nfrappe.init(site=sys.argv[1]);frappe.connect()\ntry:\n n=frappe.db.sql("select count(*) from __Auth where encrypted=1")[0][0]\n if not frappe.conf.get("encryption_key") and n: raise RuntimeError("existing_encrypted_data_without_key")\n get_encryption_key()\nfinally: frappe.destroy()\n'''
        run(['docker','exec','-u','frappe','-w',f'{BENCH}/sites',CONTAINER,f'{BENCH}/env/bin/python','-c',code,site])
        content=json.loads(config.read_text(encoding='utf-8'))
        if not content.get('encryption_key'):raise RuntimeError('encryption_key_not_persisted')
        copy_private(config,target/'site-config-with-key.json')
        results.append({'site':site,'database_bytes':dumps[0].stat().st_size,'gzip_verified':True,'key_saved':True})
    report={'directory':str(destination),'sites':results}
    (destination/'manifest.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    os.chmod(destination/'manifest.json',0o600)
    print(json.dumps(report))


if __name__=='__main__':main()

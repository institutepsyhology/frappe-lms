"""Install a published MV/IOMP contact applier without restarting containers."""
import argparse
import base64
import hashlib
import json
from pathlib import Path
import re
import shlex
import subprocess

HERE=Path(__file__).resolve().parent
REPO=HERE.parents[1]
WORKSPACE=HERE.parents[2]
SITES={'mastervision':'my-lk.mastervision.su','iomp':'my-lk.iomp.ru'}
FILES=('apply_server_contacts.py','server_contact_reader.py','mvcentr_contact_plan.py','server_archive_sink.py')

INSTALLER=r'''
import base64,hashlib,json,os,re,sys
from pathlib import Path
request=json.loads(sys.stdin.buffer.read(1024*1024))
assert set(request)=={'account','revision','files'} and re.fullmatch('[a-f0-9]{40}',request['revision'])
sites={'mastervision':'my-lk.mastervision.su','iomp':'my-lk.iomp.ru'}
assert request['account'] in sites
site=sites[request['account']]
names={'apply_server_contacts.py','server_contact_reader.py','mvcentr_contact_plan.py','server_archive_sink.py'}
assert set(request['files'])==names
base=Path('/home/frappe/frappe-bench/sites')/site/'private/apply-avo-contacts'
assert not base.is_symlink()
base.mkdir(mode=0o700,exist_ok=True);os.chmod(base,0o700)
folder=base/('release-'+request['revision']);assert not folder.is_symlink()
folder.mkdir(mode=0o700,exist_ok=True);os.chmod(folder,0o700)
hashes={}
for name,item in request['files'].items():
 assert set(item)=={'sha256','data_b64'} and re.fullmatch('[a-f0-9]{64}',item['sha256'])
 raw=base64.b64decode(item['data_b64'],validate=True)
 assert 0<len(raw)<200000 and hashlib.sha256(raw).hexdigest()==item['sha256']
 path=folder/name;assert not path.is_symlink()
 if path.exists():assert path.is_file() and path.stat().st_nlink==1 and path.read_bytes()==raw
 else:
  fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
  with os.fdopen(fd,'wb') as stream:stream.write(raw);stream.flush();os.fsync(stream.fileno())
 hashes[name]=item['sha256']
manifest={'revision':request['revision'],'files':hashes};path=folder/'manifest.json'
assert not path.is_symlink()
if path.exists():assert json.loads(path.read_text())==manifest
else:
 fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
 with os.fdopen(fd,'w') as stream:json.dump(manifest,stream,sort_keys=True)
sys.path.insert(0,str(folder));import apply_server_contacts as worker
assert worker.destination(request['account'])==site and worker.verify_release()==request['revision']
try:worker.destination('mv-centr')
except worker.ApplyError:pass
else:raise AssertionError('mvc_target_must_be_rejected')
print(json.dumps({'installed':True,'site':site,'revision':request['revision'],'files_verified':len(hashes)}))
'''


def payload(revision,account):
    if account not in SITES or not re.fullmatch('[a-f0-9]{40}',revision):raise ValueError('invalid_release_or_account')
    files={}
    for name in FILES:
        raw=subprocess.check_output(['git','show',revision+':experiments/learner-staff-sessions/'+name],cwd=REPO)
        files[name]={'sha256':hashlib.sha256(raw).hexdigest(),'data_b64':base64.b64encode(raw).decode('ascii')}
    return {'revision':revision,'account':account,'files':files}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--release',required=True);parser.add_argument('--account',required=True,choices=tuple(SITES))
    args=parser.parse_args()
    bench='/home/frappe/frappe-bench'
    remote=shlex.join(['docker','exec','-i','-u','frappe','-w',bench+'/sites','company-lms-backend-1',bench+'/env/bin/python','-B','-c',INSTALLER])
    ssh=[str(Path('C:/Windows/System32/OpenSSH/ssh.exe')),'-o','BatchMode=yes','-o','ConnectTimeout=15',
        '-o','StrictHostKeyChecking=yes','-o','UserKnownHostsFile='+str(WORKSPACE/'frappe-deploy/known_hosts'),
        '-i',str(Path.home()/'.ssh/codex_timeweb_lms_20261010'),'root@89.223.71.30',remote]
    result=subprocess.run(ssh,input=json.dumps(payload(args.release,args.account)).encode(),stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,timeout=45)
    if result.returncode:raise SystemExit('server_install_failed')
    report=json.loads(result.stdout)
    if report!={'installed':True,'site':SITES[args.account],'revision':args.release,'files_verified':len(FILES)}:
        raise SystemExit('server_install_unverified')
    print(json.dumps(report))


if __name__=='__main__':main()

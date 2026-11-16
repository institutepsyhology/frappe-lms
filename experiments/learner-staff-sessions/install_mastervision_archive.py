"""Install an exact published private server program bundle, without site updates."""
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
FILES=('audit_legacy_links.py','collect_personal_links.py','collect_personal_links_bulk.py',
    'legacy_api_snapshot.py','private_link_storage.py','progress_io.py','server_archive_sink.py','server_archive_job.py')

# Only public reviewed source enters this bootstrap. No API/site key is provided.
INSTALLER=r'''
import base64,hashlib,json,os,re,sys
from pathlib import Path
request=json.loads(sys.stdin.buffer.read(1024*1024))
assert set(request)=={'revision','files'} and re.fullmatch('[a-f0-9]{40}',request['revision'])
names={'audit_legacy_links.py','collect_personal_links.py','collect_personal_links_bulk.py','legacy_api_snapshot.py','private_link_storage.py','progress_io.py','server_archive_sink.py','server_archive_job.py'}
assert set(request['files'])==names
base=Path('/home/frappe/frappe-bench/sites/my-lk.mastervision.su/private/avo-api-archive')
assert not base.is_symlink()
base.mkdir(mode=0o700,exist_ok=True);os.chmod(base,0o700)
folder=base/('release-'+request['revision'])
assert not folder.is_symlink()
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
manifest={'revision':request['revision'],'files':hashes}
path=folder/'manifest.json';assert not path.is_symlink()
if path.exists():assert json.loads(path.read_text())==manifest
else:
 fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
 with os.fdopen(fd,'w') as stream:json.dump(manifest,stream,sort_keys=True);stream.flush();os.fsync(stream.fileno())
sys.path.insert(0,str(folder));import server_archive_job
assert server_archive_job.verify_release()==request['revision']
print(json.dumps({'installed':True,'site':'my-lk.mastervision.su','revision':request['revision'],'files_verified':len(hashes)}))
'''


def payload(revision):
    if not re.fullmatch('[a-f0-9]{40}',revision):raise ValueError('invalid_revision')
    files={}
    for name in FILES:
        raw=subprocess.check_output(['git','show',revision+':experiments/learner-staff-sessions/'+name],cwd=REPO)
        files[name]={'sha256':hashlib.sha256(raw).hexdigest(),'data_b64':base64.b64encode(raw).decode('ascii')}
    return {'revision':revision,'files':files}


def install(revision):
    bench='/home/frappe/frappe-bench'
    remote=shlex.join(['docker','exec','-i','-u','frappe','-w',bench+'/sites',
        'company-lms-backend-1',bench+'/env/bin/python','-B','-c',INSTALLER])
    args=['ssh','-o','BatchMode=yes','-o','ConnectTimeout=15','-o','StrictHostKeyChecking=yes',
        '-o','UserKnownHostsFile='+str(WORKSPACE/'frappe-deploy/known_hosts'),
        '-i',str(Path.home()/'.ssh/codex_timeweb_lms_20261010'),'root@89.223.71.30',remote]
    result=subprocess.run(args,input=json.dumps(payload(revision)).encode('utf-8'),stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,timeout=45)
    if result.returncode:raise RuntimeError('server_install_failed')
    report=json.loads(result.stdout)
    if report.get('installed') is not True or report.get('site')!='my-lk.mastervision.su' or report.get('revision')!=revision:
        raise RuntimeError('server_install_unverified')
    return report


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--release',required=True)
    args=parser.parse_args()
    try:result=install(args.release)
    except Exception:result={'installed':False,'error_code':'server_install_failed'}
    print(json.dumps(result))
    return 0 if result.get('installed') else 1


if __name__=='__main__':raise SystemExit(main())

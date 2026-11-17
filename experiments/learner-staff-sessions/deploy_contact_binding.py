"""Install published Contact identity code with persistent file overlays.

No image build or backend-container restart. Real Compose configuration and
rollback copies stay on the server; only public source bytes travel over SSH.
"""
import argparse
import base64
import hashlib
import json
from pathlib import Path
import re
import shlex
import subprocess

REPO=Path(__file__).resolve().parents[2]
WORKSPACE=REPO.parent
FILES=('lms/hooks.py','lms/lms/avo_contact_binding.py','lms/lms/avo_contact_card.py')
OLD_FILES=('lms/hooks.py','lms/lms/avo_contact_card.py')

DEPLOY=r'''
import ast,base64,hashlib,json,os,re,stat,subprocess,sys
from pathlib import Path
import yaml
r=json.loads(sys.stdin.buffer.read(1024*1024))
assert set(r)=={'revision','files','previous'} and re.fullmatch('[a-f0-9]{40}',r['revision'])
names={'lms/hooks.py','lms/lms/avo_contact_binding.py','lms/lms/avo_contact_card.py'}
assert set(r['files'])==names and set(r['previous'])==names-{'lms/lms/avo_contact_binding.py'}
services=('backend','frontend','websocket','queue-short','queue-long','scheduler')
app='/home/frappe/frappe-bench/apps/lms/'
base=Path('/opt/company-lms/overlays');base.mkdir(mode=0o700,exist_ok=True)
assert not base.is_symlink()
folder=base/('contact-binding-'+r['revision']);assert not folder.is_symlink()
folder.mkdir(mode=0o700,exist_ok=True)
config=Path('/opt/company-lms/runtime/compose.yaml');assert not config.is_symlink()
original=config.read_bytes();settings=yaml.safe_load(original)
raw_files={};hashes={}
for name,item in r['files'].items():
 assert set(item)=={'sha256','data_b64'} and re.fullmatch('[a-f0-9]{64}',item['sha256'])
 raw=base64.b64decode(item['data_b64'],validate=True)
 assert 0<len(raw)<200000 and hashlib.sha256(raw).hexdigest()==item['sha256']
 ast.parse(raw);raw_files[name]=raw;hashes[name]=item['sha256']
old_files={}
for name,item in r['previous'].items():
 raw=base64.b64decode(item['data_b64'],validate=True)
 assert hashlib.sha256(raw).hexdigest()==item['sha256']
 old_files[name]=raw
def run(args):
 p=subprocess.run(args,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL)
 if p.returncode:raise RuntimeError('server_operation_failed')
 return p.stdout
probe="import hashlib,json;from pathlib import Path;names="+repr(sorted(names))+";print(json.dumps({n:(hashlib.sha256(Path("+repr(app)+"+n).read_bytes()).hexdigest() if Path("+repr(app)+"+n).exists() else None) for n in names}))"
for service in services:
 container='company-lms-'+service+'-1'
 current=json.loads(run(['docker','exec',container,'python','-c',probe]))
 for name,digest in current.items():
  previous=r['previous'].get(name,{}).get('sha256')
  assert digest in (previous,hashes[name])
for name,raw in raw_files.items():
 path=folder/name;path.parent.mkdir(mode=0o700,parents=True,exist_ok=True);assert not path.is_symlink()
 if path.exists():assert path.read_bytes()==raw
 else:
  fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o644)
  with os.fdopen(fd,'wb') as f:f.write(raw);f.flush();os.fsync(f.fileno())
backup=folder/'compose.before.yaml'
if not backup.exists():
 fd=os.open(backup,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
 with os.fdopen(fd,'wb') as f:f.write(original)
for name,raw in old_files.items():
 path=folder/('previous-'+name.replace('/','-'))
 if not path.exists():path.write_bytes(raw);path.chmod(0o600)
for service in services:
 assert service in settings['services']
 item=settings['services'][service];volumes=list(item.get('volumes') or [])
 for name in sorted(names):
  target=app+name;new=str(folder/name)+':'+target+':ro'
  found=[v for v in volumes if isinstance(v,str) and len(v.split(':'))>=2 and v.split(':')[1]==target]
  assert not found or all(v==new for v in found)
  if not found:volumes.append(new)
 item['volumes']=volumes
updated=yaml.safe_dump(settings,sort_keys=False,allow_unicode=True).encode()
temporary=config.with_name('compose.contact-binding.tmp');assert not temporary.is_symlink()
fd=os.open(temporary,os.O_WRONLY|os.O_CREAT|os.O_TRUNC|os.O_NOFOLLOW,stat.S_IMODE(config.stat().st_mode))
with os.fdopen(fd,'wb') as f:f.write(updated);f.flush();os.fsync(f.fileno())
os.replace(temporary,config)
try:
 run(['docker','compose','--project-directory',str(config.parent),'-f',str(config),'config','--quiet'])
except BaseException:
 config.write_bytes(original)
 raise
for service in services:
 container='company-lms-'+service+'-1'
 # Activate hooks only after both referenced modules are present.
 for name in ('lms/lms/avo_contact_binding.py','lms/lms/avo_contact_card.py','lms/hooks.py'):
  target=app+name;tmp=target+'.contact-binding.tmp'
  run(['docker','cp',str(folder/name),container+':'+tmp])
  replace="import os;from pathlib import Path;p=Path("+repr(target)+");assert not p.is_symlink();os.replace("+repr(tmp)+",p);os.chmod(p,0o644)"
  run(['docker','exec','-u','root',container,'python','-c',replace])
 current=json.loads(run(['docker','exec',container,'python','-c',probe]));assert current==hashes
manifest={'revision':r['revision'],'files':hashes,'services':list(services),'persistent_overlay':True,'backend_recreated':False}
(folder/'manifest.json').write_text(json.dumps(manifest,sort_keys=True));(folder/'manifest.json').chmod(0o600)
print(json.dumps({'installed':True,**manifest}))
'''


def read_file(revision,name):
    raw=subprocess.check_output(['git','show',revision+':'+name],cwd=REPO)
    return {'sha256':hashlib.sha256(raw).hexdigest(),'data_b64':base64.b64encode(raw).decode('ascii')}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--release',required=True);p.add_argument('--baseline',required=True)
    args=p.parse_args()
    if any(not re.fullmatch('[a-f0-9]{40}',x) for x in (args.release,args.baseline)):raise SystemExit('invalid_revision')
    request={'revision':args.release,'files':{n:read_file(args.release,n) for n in FILES},
        'previous':{n:read_file(args.baseline,n) for n in OLD_FILES}}
    remote=shlex.join(['python3','-c',DEPLOY])
    command=[str(Path('C:/Windows/System32/OpenSSH/ssh.exe')),'-i',str(Path.home()/'.ssh/codex_timeweb_lms_20261010'),
        '-o','BatchMode=yes','-o','StrictHostKeyChecking=yes','-o','UserKnownHostsFile='+str(WORKSPACE/'frappe-deploy/known_hosts'),
        '-o','ConnectTimeout=15','root@89.223.71.30',remote]
    result=subprocess.run(command,input=json.dumps(request).encode(),stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,timeout=120)
    if result.returncode:raise SystemExit('source_overlay_install_failed')
    report=json.loads(result.stdout)
    if not report.get('installed') or report.get('revision')!=args.release:raise SystemExit('overlay_readback_failed')
    print(json.dumps(report))


if __name__=='__main__':main()

"""Apply the published native Contact lookup index to the selected site."""
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
PATCH='lms/patches/v2_0/add_contact_email_lookup_index.py'
SITES={'mastervision':'my-lk.mastervision.su','iomp':'my-lk.iomp.ru'}

REMOTE=r'''
import base64,hashlib,importlib.util,json,os,re,sys,time,statistics,shutil
from pathlib import Path
import frappe
request=json.loads(sys.stdin.buffer.read(1024*1024))
assert set(request)=={'revision','sha256','source_b64','account'}
assert re.fullmatch('[a-f0-9]{40}',request['revision'])
raw=base64.b64decode(request['source_b64'],validate=True)
assert len(raw)<50000 and hashlib.sha256(raw).hexdigest()==request['sha256']
site={'mastervision':'my-lk.mastervision.su','iomp':'my-lk.iomp.ru'}[request['account']]
frappe.init(site=site);frappe.connect();frappe.set_user('Administrator')
assert frappe.local.site==site and frappe.session.user=='Administrator'
private=Path(frappe.get_site_path('private')).resolve()
assert shutil.disk_usage(private).free>2*1024**3
query='SELECT parent FROM `tabContact Email` WHERE email_id=%s AND parenttype=%s'
args=('codex-index-probe@example.invalid','Contact')
def measure():
 values=[]
 for _ in range(10):
  started=time.perf_counter();frappe.db.sql(query,args);values.append((time.perf_counter()-started)*1000)
 return {'median_ms':statistics.median(values),'mean_ms':statistics.mean(values)}
result={'site':frappe.local.site,'revision':request['revision'],'before':measure(),
 'before_explain':frappe.db.sql('EXPLAIN '+query,args,as_dict=True)}
base=private/'schema-tuning'
assert not base.is_symlink();base.mkdir(mode=0o700,exist_ok=True)
folder=base/('release-'+request['revision']);assert not folder.is_symlink();folder.mkdir(mode=0o700,exist_ok=True)
path=folder/'add_contact_email_lookup_index.py';assert not path.is_symlink()
if path.exists():assert path.is_file() and path.read_bytes()==raw
else:
 fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
 with os.fdopen(fd,'wb') as stream:stream.write(raw);stream.flush();os.fsync(stream.fileno())
spec=importlib.util.spec_from_file_location('verified_contact_email_patch',path)
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
started=time.perf_counter();result['patch']=module.execute();result['ddl_seconds']=time.perf_counter()-started
result.update(after=measure(),after_explain=frappe.db.sql('EXPLAIN '+query,args,as_dict=True),
 indexes=[{'key':r[2],'column':r[4],'sequence':r[3],'non_unique':r[1]} for r in frappe.db.sql('SHOW INDEX FROM `tabContact Email`')],
 source_sha256=request['sha256'],updated_at=__import__('datetime').datetime.now(__import__('datetime').timezone.utc).isoformat())
manifest=folder/'verification.json';assert not manifest.is_symlink()
fd=os.open(manifest,os.O_WRONLY|os.O_CREAT|os.O_TRUNC|os.O_NOFOLLOW,0o600)
with os.fdopen(fd,'w') as stream:json.dump(result,stream,sort_keys=True)
frappe.destroy();print(json.dumps(result))
'''


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--release',required=True)
    parser.add_argument('--account',choices=SITES,default='mastervision')
    args=parser.parse_args()
    if not re.fullmatch('[a-f0-9]{40}',args.release):raise SystemExit('invalid_release')
    raw=subprocess.check_output(['git','show',args.release+':'+PATCH],cwd=REPO)
    request={'revision':args.release,'sha256':hashlib.sha256(raw).hexdigest(),'source_b64':base64.b64encode(raw).decode(),'account':args.account}
    bench='/home/frappe/frappe-bench'
    remote=shlex.join(['docker','exec','-i','-u','frappe','-w',bench+'/sites','company-lms-backend-1',bench+'/env/bin/python','-B','-c',REMOTE])
    command=[r'C:\Windows\System32\OpenSSH\ssh.exe','-i',str(Path.home()/'.ssh/codex_timeweb_lms_20261010'),
        '-o','BatchMode=yes','-o','StrictHostKeyChecking=yes','-o','ConnectTimeout=15',
        '-o','UserKnownHostsFile='+str(WORKSPACE/'frappe-deploy/known_hosts'),'root@89.223.71.30',remote]
    result=subprocess.run(command,input=json.dumps(request).encode(),stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,timeout=90)
    if result.returncode:raise SystemExit('index_application_not_confirmed')
    value=json.loads(result.stdout)
    if value.get('site')!=SITES[args.account] or not value.get('after_explain') or value['after_explain'][0].get('type')=='ALL':
        raise SystemExit('index_readback_failed')
    print(json.dumps(value))


if __name__=='__main__':main()

"""Apply published selected-MV speed controls without restarting the link job."""
import argparse
import json
from pathlib import Path
import re
import shlex
import subprocess

HERE=Path(__file__).resolve().parent
WORKSPACE=HERE.parents[2]

REMOTE=r'''
import json,os,sys,time
from pathlib import Path
request=json.loads(sys.stdin.buffer.read(4097))
assert set(request)=={'revision','selection','api_speed'}
revision=request['revision'];fingerprint=request['selection'];speed=request['api_speed']
assert isinstance(revision,str) and len(revision)==40 and all(c in '0123456789abcdef' for c in revision)
assert type(speed) in (int,float) and 0<speed<=5
private=Path('/home/frappe/frappe-bench/sites/my-lk.mastervision.su/private')
sys.path.insert(0,str(private/'apply-avo-contacts'/('release-'+revision)))
import apply_server_contacts as worker
assert worker.verify_release()==revision
_,folder=worker.read_selection('mastervision',fingerprint)
assert all((private.parents[1]/site/'private'/job/'STOP').exists()
 for site in ('my-lk.mastervision.su','my-lk.iomp.ru')
 for job in ('apply-avo-contacts','avo-api-archive/job-20261116'))
application=folder/'application';individual=folder/'individual'
assert application.is_dir() and individual.is_dir()
stop=worker.safe_file(application/'STOP');marker='operator-selected-speed-upgrade'
if stop.exists():assert stop.read_text()==marker
else:
 fd=os.open(stop,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
 with os.fdopen(fd,'w') as stream:stream.write(marker)
for _ in range(100):
 try:
  with worker.lock(private/'apply-avo-contacts'):pass
  break
 except worker.ApplyError:time.sleep(.2)
else:raise RuntimeError('previous_writer_still_active')
settings=worker.safe_file(individual/'speed.json');tmp=worker.safe_file(individual/'speed.operator.tmp')
fd=os.open(tmp,os.O_WRONLY|os.O_CREAT|os.O_TRUNC|os.O_NOFOLLOW,0o600)
with os.fdopen(fd,'w') as stream:
 json.dump({'requests_per_second':speed},stream);stream.flush();os.fsync(stream.fileno())
os.replace(tmp,settings)
assert stop.read_text()==marker;stop.unlink()
result=worker.launch('mastervision',retry_issues=True,selection=fingerprint)
result.update(revision=revision,individual_job_restarted=False,api_target_requests_per_second=speed,general_pauses_preserved=True)
print(json.dumps(result))
'''


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--release',required=True);parser.add_argument('--selection',required=True)
    parser.add_argument('--api-speed',required=True,type=float)
    args=parser.parse_args()
    if (not re.fullmatch('[a-f0-9]{40}',args.release) or not re.fullmatch('[a-f0-9]{64}',args.selection)
            or not 0<args.api_speed<=5):raise SystemExit('invalid_control')
    bench='/home/frappe/frappe-bench'
    remote=shlex.join(['docker','exec','-i','-u','frappe','-w',bench+'/sites',
        'company-lms-backend-1',bench+'/env/bin/python','-B','-c',REMOTE])
    command=[r'C:\Windows\System32\OpenSSH\ssh.exe','-i',str(Path.home()/'.ssh/codex_timeweb_lms_20261010'),
        '-o','BatchMode=yes','-o','StrictHostKeyChecking=yes','-o','ConnectTimeout=15',
        '-o','UserKnownHostsFile='+str(WORKSPACE/'frappe-deploy/known_hosts'),'root@89.223.71.30',remote]
    result=subprocess.run(command,input=json.dumps({'revision':args.release,'selection':args.selection,'api_speed':args.api_speed}).encode(),
        stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,timeout=60)
    if result.returncode:raise SystemExit('control_not_confirmed')
    response=json.loads(result.stdout)
    if (response.get('status')!='starting' or response.get('account')!='mastervision'
            or response.get('individual_job_restarted') is not False
            or response.get('general_pauses_preserved') is not True):raise SystemExit('control_not_verified')
    print(json.dumps(response))


if __name__=='__main__':main()

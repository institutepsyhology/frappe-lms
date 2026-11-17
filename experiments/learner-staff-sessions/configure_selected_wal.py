"""Tune only the selected MV private ledgers; preserve FULL durability."""
import argparse
import base64
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import sqlite3
import subprocess
import time

ACCOUNT='mastervision'
SITE='my-lk.mastervision.su'
HERE=Path(__file__).resolve().parent
REPO=HERE.parents[1]
WORKSPACE=HERE.parents[2]
SOURCE='experiments/learner-staff-sessions/configure_selected_wal.py'


def configure_file(path,scope,kind,*,connect=sqlite3.connect):
    path=Path(path)
    if (path.is_symlink() or not path.is_file() or path.stat().st_nlink!=1
            or kind not in ('application','individual') or not re.fullmatch('[a-f0-9]{64}',scope)):
        raise ValueError('unsafe_private_database')
    with closing(connect(path.resolve().as_uri()+'?mode=rw',uri=True,timeout=.25,isolation_level=None)) as db:
        metadata=dict(db.execute('SELECT key,value FROM metadata'))
        if kind=='application':
            valid=(set(metadata)=={'account','site','snapshot'} and metadata.get('account')==ACCOUNT
                and metadata.get('site')==SITE and re.fullmatch('[a-f0-9]{32}:'+scope,metadata.get('snapshot','')))
        else:
            valid=metadata=={'format':'selected-mv-profile-v1','account':ACCOUNT,'site':SITE,'selection':scope}
        if not valid:raise ValueError('private_identity_mismatch')
        # Existing writers explicitly set FULL too. This new connection never
        # downgrades synchronous, and changes only the persistent journal mode.
        db.execute('PRAGMA synchronous=FULL')
        before=db.execute('PRAGMA journal_mode').fetchone()[0]
        if before not in ('delete','wal'):raise ValueError('unexpected_journal_mode')
        if before!='wal':
            deadline=time.monotonic()+2
            while True:
                try:
                    after=db.execute('PRAGMA journal_mode=WAL').fetchone()[0]
                    break
                except sqlite3.OperationalError as error:
                    code=getattr(error,'sqlite_errorcode',None)
                    if code not in (sqlite3.SQLITE_BUSY,sqlite3.SQLITE_LOCKED):raise
                    if time.monotonic()>=deadline:return {'database':kind,'status':'busy_unchanged','before':before}
                    time.sleep(.05)
        else:after=before
        sync=db.execute('PRAGMA synchronous').fetchone()[0]
        if after!='wal' or sync!=2:raise ValueError('durability_readback_failed')
        return {'database':kind,'status':'configured','before':before,'after':after,'synchronous':sync}


REMOTE=r'''
import base64,hashlib,json,os,re,shutil,sys,time
from pathlib import Path
request=json.loads(sys.stdin.buffer.read(1024*1024))
assert set(request)=={'revision','scope','source_b64','sha256'}
assert re.fullmatch('[a-f0-9]{40}',request['revision']) and re.fullmatch('[a-f0-9]{64}',request['scope'])
raw=base64.b64decode(request['source_b64'],validate=True)
assert len(raw)<50000 and hashlib.sha256(raw).hexdigest()==request['sha256']
root=Path('/home/frappe/frappe-bench/sites/my-lk.mastervision.su/private')
folder=root/'selected-contacts'/request['scope'];assert not folder.is_symlink()
assert shutil.disk_usage(folder).free>2*1024**3
selection=json.loads((folder/'selection.json').read_text())
assert selection['manifest']['account']=='mastervision' and selection['manifest']['fingerprint']==request['scope']
modules={'__name__':'published_wal_tuning','__file__':str(folder/'published-wal-tuning.py')}
exec(compile(raw,'published-wal-tuning.py','exec'),modules)
results=[]
for kind,filename in [('application','state.sqlite'),('individual','profiles.sqlite')]:
 path=folder/kind/filename
 assert path.stat().st_uid==os.getuid()
 results.append(modules['configure_file'](path,request['scope'],kind))
result={'site':'my-lk.mastervision.su','revision':request['revision'],'sha256':request['sha256'],'databases':results,'workers_restarted':False}
path=folder/'wal-tuning.json';assert not path.is_symlink()
fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_TRUNC|os.O_NOFOLLOW,0o600)
with os.fdopen(fd,'w') as stream:json.dump(result,stream,sort_keys=True)
print(json.dumps(result))
'''


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--release',required=True);parser.add_argument('--selection',required=True)
    args=parser.parse_args()
    if not re.fullmatch('[a-f0-9]{40}',args.release) or not re.fullmatch('[a-f0-9]{64}',args.selection):raise SystemExit('invalid_arguments')
    raw=subprocess.check_output(['git','show',args.release+':'+SOURCE],cwd=REPO)
    request={'revision':args.release,'scope':args.selection,'source_b64':base64.b64encode(raw).decode(),'sha256':hashlib.sha256(raw).hexdigest()}
    bench='/home/frappe/frappe-bench'
    remote=shlex.join(['docker','exec','-i','-u','frappe','-w',bench+'/sites','company-lms-backend-1',bench+'/env/bin/python','-B','-c',REMOTE])
    command=[r'C:\Windows\System32\OpenSSH\ssh.exe','-i',str(Path.home()/'.ssh/codex_timeweb_lms_20261010'),
        '-o','BatchMode=yes','-o','StrictHostKeyChecking=yes','-o','ConnectTimeout=15',
        '-o','UserKnownHostsFile='+str(WORKSPACE/'frappe-deploy/known_hosts'),'root@89.223.71.30',remote]
    result=subprocess.run(command,input=json.dumps(request).encode(),stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,timeout=30)
    if result.returncode:raise SystemExit('wal_tuning_not_confirmed')
    print(result.stdout.decode())


if __name__=='__main__':main()

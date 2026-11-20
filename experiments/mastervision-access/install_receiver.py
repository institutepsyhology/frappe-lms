"""Publish just the capture receiver to Master Vision's private site directory."""
import hashlib
from pathlib import Path
import shlex
import subprocess

HERE = Path(__file__).resolve().parent
SSH = Path('C:/Windows/System32/OpenSSH/ssh.exe')
BASE = '/home/frappe/frappe-bench/sites/my-lk.mastervision.su/private/mv-course-access'
DEPLOY = """import hashlib, os, sys, tempfile
from pathlib import Path
root=Path(sys.argv[1])
data=sys.stdin.buffer.read(1000000)
assert len(data)<1000000 and hashlib.sha256(data).hexdigest()==sys.argv[2]
compile(data,'archive_store.py','exec')
os.umask(0o077)
root.mkdir(mode=0o700,parents=True,exist_ok=True)
assert root.resolve()==root and not (root.stat().st_mode & 0o077)
dest=root/'archive_store.py'
assert not dest.is_symlink()
if not dest.exists() or dest.read_bytes()!=data:
    with tempfile.NamedTemporaryFile(dir=root, prefix='receiver-', delete=False) as stage:
        stage.write(data)
        stage.flush()
        os.fsync(stage.fileno())
    os.replace(stage.name,dest)
print(hashlib.sha256(dest.read_bytes()).hexdigest())
"""


def main():
    data=(HERE/'archive_store.py').read_bytes()
    digest=hashlib.sha256(data).hexdigest()
    command=shlex.join(['docker','exec','-i','-u','frappe','company-lms-backend-1',
                        '/home/frappe/frappe-bench/env/bin/python','-B','-c',DEPLOY, BASE,digest])
    cmd=[str(SSH),'-o','BatchMode=yes','-o','ConnectTimeout=15','-o','IdentitiesOnly=yes',
         '-o','StrictHostKeyChecking=yes','-o','UserKnownHostsFile='+str(HERE.parents[2]/'frappe-deploy/known_hosts'),
         '-i',str(Path.home()/'.ssh/codex_timeweb_lms_20261010'),'root@89.223.71.30',command]
    result=subprocess.run(cmd,input=data,stdout=subprocess.PIPE,check=True,timeout=60)
    if result.stdout.strip()!=digest.encode():
        raise SystemExit('Receiver verification failed')
    print('Verified receiver',digest)


if __name__=='__main__':
    main()

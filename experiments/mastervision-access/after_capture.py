"""Continue this fixed MV migration after the browser has finished the card archive."""
import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys
import time

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
BENCH = '/home/frappe/frappe-bench'
SITE = 'my-lk.mastervision.su'
BASE = f'{BENCH}/sites/{SITE}/private/mv-course-access'
DATA = BASE + '/through-446858-20261120'
PY = BENCH + '/env/bin/python'
FILES = (
    'mastervision-access/target_archive.py', 'mastervision-access/target_sync.py',
    'mastervision-access/course_rules.py', 'mastervision-access/server_apply.py',
    'mastervision-migration/lesson_policy.py', 'mastervision-migration/importer.py',
    'mastervision-migration/persistent_https.py', 'avo-batch-import/support/collector/lesson_content/packed.py',
)


def remote(argv, *, payload=None, detached=False, timeout=90):
    ssh = Path(os.environ['SystemRoot']) / 'System32/OpenSSH/ssh.exe'
    cmd = ['docker', 'exec', '-d' if detached else '-i', '-u', 'frappe', '-w',
           BENCH + '/sites', 'company-lms-backend-1', PY, '-B', *argv]
    return subprocess.run([str(ssh), '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=15',
                           '-o', 'StrictHostKeyChecking=yes', '-o', 'IdentitiesOnly=yes',
                           '-o', 'UserKnownHostsFile=' + str(REPO.parent / 'frappe-deploy/known_hosts'),
                           '-i', str(Path.home() / '.ssh/codex_timeweb_lms_20261010'), 'root@89.223.71.30',
                           shlex.join(cmd)], input=payload, capture_output=True, timeout=timeout, check=True).stdout


INSTALL = """import hashlib,json,os,sys,base64,tempfile
from pathlib import Path
root=Path(sys.argv[1])
assert root.resolve()==root and root.parents[2].name=='mv-course-access'
os.umask(0o077)
req=json.load(sys.stdin)
assert sorted(req)==sorted(sys.argv[2:])
for name,(digest,encoded) in req.items():
    dest=root/'experiments'/name
    assert '..' not in Path(name).parts and dest.resolve()==dest and root in dest.parents
    data=base64.b64decode(encoded,validate=True)
    assert len(data)<1000000 and hashlib.sha256(data).hexdigest()==digest
    compile(data,str(dest),'exec')
    dest.parent.mkdir(mode=0o700,parents=True,exist_ok=True)
    if dest.exists():
        assert dest.read_bytes()==data
        continue
    with tempfile.NamedTemporaryFile(dir=dest.parent,delete=False) as temp:
        temp.write(data)
        temp.flush()
        os.fsync(temp.fileno())
    os.replace(temp.name,dest)
print('verified')"""


def release():
    rev = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=REPO, text=True).strip()
    if not re.fullmatch('[a-f0-9]{40}', rev):
        raise ValueError('unknown_revision')
    # Only code blobs from this published revision are eligible for installation.
    out = subprocess.check_output(['git', 'ls-remote', '--exit-code', 'origin',
                                  'refs/heads/feature/avo-mcp-import-20261103'], cwd=REPO, text=True)
    if not out.startswith(rev + '\t'):
        raise ValueError('revision_not_published')
    root = f'{DATA}/releases/{rev}'
    files = {}
    for name in FILES:
        raw = subprocess.check_output(['git', 'show', rev + ':experiments/' + name], cwd=REPO)
        files[name] = [hashlib.sha256(raw).hexdigest(), base64.b64encode(raw).decode()]
    if remote(['-c', INSTALL, root, *FILES], payload=json.dumps(files).encode()).strip() != b'verified':
        raise ValueError('install_incomplete')
    return rev


def status():
    return json.loads(remote([BASE + '/archive_store.py', '--status']))


def process_alive(pid):
    import ctypes
    from ctypes import wintypes
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.OpenProcess.restype = wintypes.HANDLE
    handle = kernel.OpenProcess(0x00100000, False, pid)
    if not handle:
        if ctypes.get_last_error() == 87:
            return False
        raise OSError(ctypes.get_last_error(), 'cannot_check_collector')
    try:
        return kernel.WaitForSingleObject(wintypes.HANDLE(handle), 0) == 258
    finally:
        kernel.CloseHandle(wintypes.HANDLE(handle))


def follow(rev, capture_pid):
    if not re.fullmatch('[a-f0-9]{40}', rev):
        raise ValueError('unknown_revision')
    for name in ['course_policy_capture.cjs', 'capture_worker.cjs', 'access_parser.cjs']:
        blob = subprocess.check_output(['git', 'show', rev + ':experiments/mastervision-access/' + name], cwd=REPO)
        if (HERE / name).read_bytes().replace(b'\r\n', b'\n') != blob.replace(b'\r\n', b'\n'):
            raise ValueError('collector_revision_changed')
    node = str(Path(os.environ['ProgramFiles'])/'nodejs/node.exe')
    capture = str(HERE/'capture_worker.cjs')
    recovered = False
    while True:
        try:
            state = status()
        except (OSError, subprocess.SubprocessError, ValueError):
            time.sleep(60)
            continue
        if state.get('state') == 'complete':
            break
        if capture_pid and not process_alive(capture_pid):
            if recovered:
                raise ValueError('capture_stopped_before_verification')
            recovered = True
            time.sleep(15)
            result = subprocess.run([node, capture, '--workers', '6'], cwd=REPO)
            if result.returncode:
                raise ValueError('capture_requires_attention')
        time.sleep(60)
    # The read-only receiver status can become complete just before its browser exits.
    for attempt in range(6):
        result = subprocess.run([node, str(HERE/'course_policy_capture.cjs')], cwd=REPO)
        if result.returncode == 0:
            break
        time.sleep(min(120, 10 * (attempt + 1)))
    else:
        raise ValueError('course_policies_incomplete')
    runner = f'{DATA}/releases/{rev}/experiments/mastervision-access/server_apply.py'
    remote([runner], detached=True)
    print('target_job_dispatched', flush=True)


if __name__ == '__main__':
    args = argparse.ArgumentParser()
    actions = args.add_mutually_exclusive_group(required=True)
    actions.add_argument('--install', action='store_true')
    actions.add_argument('--follow')
    actions.add_argument('--status', action='store_true')
    args.add_argument('--capture-pid', type=int)
    opts = args.parse_args()
    if opts.install:
        print(release())
    elif opts.status:
        print(json.dumps(status()))
    else:
        follow(opts.follow, opts.capture_pid)

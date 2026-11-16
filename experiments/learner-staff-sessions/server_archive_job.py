"""Isolated MV/IOMP server job; the API key travels only via stdin pipes."""
import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import json
import hashlib
import os
from pathlib import Path
import re
import subprocess
import sys
import time
from types import MappingProxyType


class JobError(Exception):pass


SERVER_ACCOUNTS=MappingProxyType({
    'mastervision':('my-lk.mastervision.su','https://shop.mastervision.su'),
    'iomp':('my-lk.iomp.ru','https://shop.iomp.ru'),
})
# A trusted startup selector fixes one account before any core module or key is
# read. It never comes from the stdin envelope and is inherited by its child.
ACCOUNT=os.environ.get('AVO_SERVER_ARCHIVE_ACCOUNT','mastervision')
if ACCOUNT not in SERVER_ACCOUNTS:raise JobError('wrong_account')
SITE,API_ORIGIN=SERVER_ACCOUNTS[ACCOUNT]
BASE=Path('/home/frappe/frappe-bench/sites')/SITE/'private'/'avo-api-archive'
JOB=BASE/'job-20261116'
SAFE_CODES={'already_running','paused','wrong_account','invalid_key_input','invalid_release',
    'worker_start_failed','worker_stopped','server_job_failed','missing_site_key','unsafe_job_path'}


RELEASE_FILES=('audit_legacy_links.py','collect_personal_links.py','collect_personal_links_bulk.py',
    'legacy_api_snapshot.py','private_link_storage.py','progress_io.py','server_archive_sink.py','server_archive_job.py')


def verify_release():
    folder=Path(__file__).resolve().parent
    if not re.fullmatch(r'release-[a-f0-9]{40}',folder.name):raise JobError('invalid_release')
    try:
        manifest=json.loads(checked_path(folder/'manifest.json').read_text(encoding='utf-8'))
        if (set(manifest)!={'revision','files'} or manifest['revision']!=folder.name[8:]
                or set(manifest['files'])!=set(RELEASE_FILES)):raise JobError('invalid_release')
        for name,digest in manifest['files'].items():
            if hashlib.sha256(checked_path(folder/name).read_bytes()).hexdigest()!=digest:
                raise JobError('invalid_release')
    except (OSError,ValueError,TypeError):raise JobError('invalid_release') from None
    return manifest['revision']


def private_directory(path):
    path=Path(path)
    if path.is_symlink():raise JobError('unsafe_job_path')
    path.mkdir(mode=0o700,exist_ok=True)
    if not path.is_dir() or path.stat().st_uid!=os.getuid():raise JobError('unsafe_job_path')
    os.chmod(path,0o700)
    return path


def checked_path(path):
    path=Path(path)
    if path.is_symlink() or path.exists() and (not path.is_file() or path.stat().st_nlink!=1):
        raise JobError('unsafe_job_path')
    return path


def validate_key(value):
    if (not isinstance(value,str) or not 1<=len(value)<=512
            or any(ord(c)<33 or ord(c)==127 for c in value) or '://' in value):
        raise JobError('invalid_key_input')
    return value


def read_key(stream):
    raw=stream.read(4097)
    if len(raw)>4096:raise JobError('invalid_key_input')
    try:payload=json.loads(raw)
    except (ValueError,UnicodeError):raise JobError('invalid_key_input') from None
    if not isinstance(payload,dict) or set(payload)!={'key'}:raise JobError('invalid_key_input')
    return validate_key(payload['key'])


@contextmanager
def lock(path):
    import fcntl
    checked_path(path)
    descriptor=os.open(path,os.O_RDWR|os.O_CREAT|os.O_NOFOLLOW,0o600)
    try:
        try:fcntl.flock(descriptor,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:raise JobError('already_running') from None
        yield
    finally:os.close(descriptor)


def write_status(value):
    from progress_io import write_json
    write_json(JOB/'server-status.json',dict(value,account=ACCOUNT,site=SITE,
        updated_at=datetime.now(timezone.utc).isoformat(),key_saved=False))


def bound_runtime():
    # This process has exactly one account. Never alter a shared running worker.
    value=os.environ.get('AVO_ARCHIVE_ACCOUNT')
    if value not in (None,ACCOUNT):raise JobError('wrong_account')
    os.environ['AVO_ARCHIVE_ACCOUNT']=ACCOUNT
    from server_archive_sink import PROFILE,runtime_archive
    from private_link_storage import configure_server_cipher
    if PROFILE.account!=ACCOUNT or PROFILE.site!=SITE or PROFILE.api_origin!=API_ORIGIN:
        raise JobError('wrong_account')
    _,cipher=runtime_archive()
    configure_server_cipher(cipher,ACCOUNT)
    return PROFILE


def run_worker():
    private_directory(BASE);private_directory(JOB)
    with lock(JOB/'server-worker.lock'):
        write_status({'status':'initializing','worker_pid':os.getpid()})
        key=None
        try:
            bound_runtime()
            key=read_key(sys.stdin.buffer)
            if (JOB/'STOP').exists():raise JobError('paused')
            from legacy_api_snapshot import collect
            write_status({'status':'collecting','worker_pid':os.getpid()})
            report=collect(JOB,account=ACCOUNT,key=key,collect_links=True,
                requests_per_second=1.0,link_requests_per_second=1.0)
            write_status({'status':report['status'],'error_code':report.get('error_code'),
                          'worker_pid':os.getpid(),'links_status':report.get('links_status')})
            return {'status':report['status'],'error_code':report.get('error_code')}
        finally:key=None


def launch_worker():
    private_directory(BASE);private_directory(JOB)
    if (JOB/'STOP').exists():raise JobError('paused')
    program=Path(__file__).resolve()
    if not re.fullmatch(r'release-[a-f0-9]{40}',program.parent.name):raise JobError('invalid_release')
    with lock(JOB/'server-launch.lock'):
        with lock(JOB/'server-worker.lock'):pass
        key=read_key(sys.stdin.buffer)
        log=checked_path(JOB/'worker.log')
        descriptor=os.open(log,os.O_WRONLY|os.O_CREAT|os.O_APPEND|os.O_NOFOLLOW,0o600)
        try:
            with os.fdopen(descriptor,'ab',buffering=0) as stream:
                child=subprocess.Popen([sys.executable,'-B',str(program),'--run'],stdin=subprocess.PIPE,
                    stdout=stream,stderr=stream,start_new_session=True,close_fds=True)
                try:
                    child.stdin.write(json.dumps({'key':key}).encode('utf-8'))
                    child.stdin.close()
                finally:key=None
                # The child owns a separate session and output handles. Readiness
                # comes from its lock/status rather than an open SSH connection.
                deadline=time.monotonic()+12
                while time.monotonic()<deadline:
                    if child.poll() is not None:raise JobError('worker_start_failed')
                    try:
                        status=json.loads((JOB/'server-status.json').read_text())
                        if status.get('worker_pid')==child.pid and status.get('status')=='collecting':
                            return {'status':'started','site':SITE,'account':ACCOUNT,'worker_pid':child.pid,
                                    'job_directory':str(JOB),'key_saved':False}
                    except (OSError,ValueError):pass
                    time.sleep(0.1)
                return {'status':'starting','site':SITE,'account':ACCOUNT,'worker_pid':child.pid,
                        'job_directory':str(JOB),'key_saved':False}
        finally:key=None


def main():
    is_worker=False
    try:
        parser=argparse.ArgumentParser(description=__doc__)
        parser.add_argument('--run',action='store_true')
        parser.add_argument('--start',action='store_true')
        args=parser.parse_args()
        if args.run==args.start:raise JobError('server_job_failed')
        is_worker=args.run
        verify_release()
        result=run_worker() if args.run else launch_worker()
        code=0
    except Exception as error:
        safe=error.args[0] if isinstance(error,JobError) and len(error.args)==1 else 'server_job_failed'
        if safe not in SAFE_CODES:safe='server_job_failed'
        result={'status':'stopped','error_code':safe,'account':ACCOUNT,'site':SITE,'key_saved':False}
        try:
            if is_worker and JOB.is_dir() and not JOB.is_symlink():
                write_status(dict(result,error_type=type(error).__name__))
        except Exception:pass
        code=1
    print(json.dumps(result,ensure_ascii=True))
    return code


if __name__=='__main__':raise SystemExit(main())

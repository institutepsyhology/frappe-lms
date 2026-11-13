"""Launch a private migration job from a verified committed public-code snapshot."""
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import sys
import tarfile
from datetime import datetime, timezone
import uuid

SCRIPT = Path(__file__).resolve()
REPO = SCRIPT.parents[2]
PREFIX = 'experiments/mastervision-migration/'
ENTRY = PREFIX + 'run.py'
MONITOR = PREFIX + 'launch.py'
SUPPORT = ('lms/lms/avo_html_fragment.py', 'lms/lms/avo_transform.py',
           'lms/__init__.py', 'lms/lms/__init__.py',
           'experiments/avo-batch-import/support/collector/lesson_content/packed.py')
ARCHIVE_PATHS = (PREFIX.rstrip('/'), *SUPPORT)
REQUIRED = {ENTRY, MONITOR, *SUPPORT}
MANIFEST = 'source-manifest.json'
MAX_SOURCE_BYTES = 2 * 1024 * 1024
MAX_ARCHIVE_BYTES = 4 * 1024 * 1024
MAX_META_BYTES = 128 * 1024
BOOL_FLAGS = {'--apply', '--stored', '--resume', '--collect-only', '--catalog-only', '--covers-only', '--settings-only', '--review-only'}
INT_FLAGS = {'--from-course', '--limit', '--course'}
JOB_KEYS = {'version', 'job_id', 'workspace', 'source_commit', 'source_manifest_sha256',
            'arguments', 'status', 'monitor_pid', 'pid', 'created_at_utc', 'started_at_utc',
            'finished_at_utc', 'exit_code', 'error'}


class LaunchError(RuntimeError):
    """Fixed diagnostic code only, never stderr, source bodies or credentials."""


def _now(): return datetime.now(timezone.utc).isoformat()
def _sha(value): return hashlib.sha256(value).hexdigest()
def _json(value): return (json.dumps(value, sort_keys=True, ensure_ascii=True, separators=(',', ':')) + '\n').encode()


def _reparse(path):
    return path.is_symlink() or (hasattr(path, 'is_junction') and path.is_junction())


def _under(root, relative):
    path = root.joinpath(*PurePosixPath(relative).parts)
    if not path.resolve().is_relative_to(root.resolve()): raise LaunchError('unsafe_job_path')
    current = root
    for part in PurePosixPath(relative).parts:
        current = current / part
        if _reparse(current): raise LaunchError('unsafe_job_path')
    return path


def _workspace(value=None):
    explicit = value if value is not None else os.environ.get('MASTER_VISION_WORKSPACE')
    candidates = [Path(explicit)] if explicit else list(SCRIPT.parents)
    for candidate in candidates:
        try: candidate = candidate.resolve(strict=True)
        except OSError: continue
        if candidate.is_dir() and (candidate / 'frappe-mcp/headers.py').is_file(): return candidate
    raise LaunchError('workspace_not_found')


def _data(workspace): return _under(workspace, 'exports/lesson-content/mastervision-migration')


def _directory(path):
    path.mkdir(parents=True, exist_ok=True)
    if _reparse(path): raise LaunchError('unsafe_job_path')
    if os.name != 'nt': path.chmod(0o700)


def validate_flags(arguments):
    if not isinstance(arguments, list) or len(arguments) > 256:
        raise LaunchError('invalid_run_argument')
    result, seen, courses, index = [], set(), set(), 0
    while index < len(arguments):
        flag = arguments[index]
        if not isinstance(flag, str) or flag in seen and flag != '--course' or flag not in BOOL_FLAGS | INT_FLAGS:
            raise LaunchError('invalid_run_argument')
        seen.add(flag); result.append(flag); index += 1
        if flag in INT_FLAGS:
            if index >= len(arguments) or not isinstance(arguments[index], str) or not re.fullmatch('[1-9][0-9]{0,9}', arguments[index]):
                raise LaunchError('invalid_run_argument')
            if int(arguments[index]) > 2147483647: raise LaunchError('invalid_run_argument')
            if flag == '--course':
                if arguments[index] in courses: raise LaunchError('invalid_run_argument')
                courses.add(arguments[index])
            result.append(arguments[index]); index += 1
    return result


def parse_arguments(arguments):
    if len(arguments) == 2 and arguments[0] == '--monitor':
        return {'monitor': arguments[1]}
    revision, forwarded, index, revision_seen = 'HEAD', [], 0, False
    while index < len(arguments):
        if arguments[index] == '--revision':
            if revision_seen or index + 1 >= len(arguments): raise LaunchError('invalid_revision')
            revision, revision_seen = arguments[index + 1], True
            index += 2
        else:
            forwarded.append(arguments[index]); index += 1
    if not isinstance(revision, str) or not re.fullmatch('[A-Za-z0-9][A-Za-z0-9._/-]{0,199}', revision) or '..' in revision:
        raise LaunchError('invalid_revision')
    return {'revision': revision, 'arguments': validate_flags(forwarded)}


def _git(repo, arguments):
    try:
        result = subprocess.run(['git', '-C', str(repo), *arguments], stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, check=True, timeout=30,
            env={**os.environ, 'GIT_OPTIONAL_LOCKS': '0'},
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    except (OSError, subprocess.SubprocessError): raise LaunchError('committed_source_unavailable') from None
    if len(result.stdout) > MAX_ARCHIVE_BYTES: raise LaunchError('archive_size_invalid')
    return result.stdout


def _relative(name):
    if (not isinstance(name, str) or not name or '\\' in name or ':' in name or '\x00' in name
            or name.startswith('/') or any(part in ('', '.', '..') for part in name.rstrip('/').split('/'))):
        raise LaunchError('unsafe_archive_path')
    return name.rstrip('/')


def _public_file(name):
    return name in SUPPORT or (name.startswith(PREFIX) and PurePosixPath(name).suffix in {'.py', '.cjs', '.md'})


def archive_sources(raw):
    if not isinstance(raw, bytes) or len(raw) > MAX_ARCHIVE_BYTES: raise LaunchError('archive_size_invalid')
    sources, seen, total = {}, set(), 0
    ancestors = {str(parent) for name in ARCHIVE_PATHS for parent in PurePosixPath(name).parents if str(parent) != '.'}
    ancestors.add(PREFIX.rstrip('/'))
    try:
        with tarfile.open(fileobj=io.BytesIO(raw), mode='r:') as archive:
            for index, member in enumerate(archive):
                if index >= 512: raise LaunchError('archive_size_invalid')
                name = _relative(member.name)
                if name in seen: raise LaunchError('duplicate_archive_path')
                seen.add(name)
                if member.isdir():
                    if name not in ancestors and not name.startswith(PREFIX): raise LaunchError('unexpected_archive_path')
                    continue
                if not member.isfile(): raise LaunchError('archive_links_forbidden')
                if not _public_file(name): raise LaunchError('unexpected_archive_path')
                if member.size < 0 or member.size > MAX_SOURCE_BYTES: raise LaunchError('archive_size_invalid')
                total += member.size
                if total > MAX_SOURCE_BYTES or len(sources) >= 256: raise LaunchError('archive_size_invalid')
                with archive.extractfile(member) as stream: content = stream.read(member.size + 1)
                if len(content) != member.size: raise LaunchError('archive_content_invalid')
                sources[name] = content
    except (tarfile.TarError, OSError, ValueError): raise LaunchError('archive_content_invalid') from None
    if not REQUIRED.issubset(sources): raise LaunchError('required_source_missing')
    return sources


def _tree_files(root):
    files, pending = set(), [root]
    while pending:
        directory = pending.pop()
        for path in directory.iterdir():
            if _reparse(path): raise LaunchError('cache_integrity_invalid')
            if path.is_dir(): pending.append(path)
            elif path.is_file(): files.add(path.relative_to(root).as_posix())
            else: raise LaunchError('cache_integrity_invalid')
            if len(files) + len(pending) > 1024: raise LaunchError('cache_integrity_invalid')
    return files


def verify_cache(cache, commit, expected_manifest=None):
    if not re.fullmatch('[0-9a-f]{40}', commit): raise LaunchError('invalid_source_commit')
    if not cache.is_dir() or _reparse(cache): raise LaunchError('cache_integrity_invalid')
    manifest_file = _under(cache, MANIFEST)
    if not manifest_file.is_file() or manifest_file.stat().st_size > MAX_META_BYTES: raise LaunchError('cache_integrity_invalid')
    raw = manifest_file.read_bytes()
    try: manifest = json.loads(raw)
    except (ValueError, UnicodeError): raise LaunchError('cache_integrity_invalid') from None
    if (not isinstance(manifest, dict) or set(manifest) != {'version', 'source_commit', 'files', 'total_bytes'}
            or manifest['version'] != 1 or manifest['source_commit'] != commit
            or not isinstance(manifest['files'], dict) or len(manifest['files']) > 256
            or not REQUIRED.issubset(manifest['files']) or raw != _json(manifest)
            or expected_manifest is not None and raw != expected_manifest):
        raise LaunchError('cache_integrity_invalid')
    if _tree_files(cache) != set(manifest['files']) | {MANIFEST}: raise LaunchError('cache_integrity_invalid')
    total = 0
    for name, digest in manifest['files'].items():
        _relative(name)
        if not _public_file(name) or not isinstance(digest, str) or not re.fullmatch('[0-9a-f]{64}', digest):
            raise LaunchError('cache_integrity_invalid')
        file = _under(cache, name)
        size = file.stat().st_size
        total += size
        if size > MAX_SOURCE_BYTES or total > MAX_SOURCE_BYTES or _sha(file.read_bytes()) != digest:
            raise LaunchError('cache_integrity_invalid')
    if type(manifest['total_bytes']) is not int or manifest['total_bytes'] != total:
        raise LaunchError('cache_integrity_invalid')
    return _sha(raw)


def prepare_code(repo, workspace, revision='HEAD'):
    repo, workspace = Path(repo).resolve(strict=True), _workspace(workspace)
    if not isinstance(revision, str) or not re.fullmatch('[A-Za-z0-9][A-Za-z0-9._/-]{0,199}', revision) or '..' in revision:
        raise LaunchError('invalid_revision')
    try: commit = _git(repo, ['rev-parse', '--verify', revision + '^{commit}']).decode('ascii').strip()
    except UnicodeError: raise LaunchError('invalid_source_commit') from None
    if not re.fullmatch('[0-9a-f]{40}', commit): raise LaunchError('invalid_source_commit')
    sources = archive_sources(_git(repo, ['archive', '--format=tar', commit, '--', *ARCHIVE_PATHS]))
    manifest = _json({'version': 1, 'source_commit': commit,
        'files': {name: _sha(content) for name, content in sources.items()},
        'total_bytes': sum(map(len, sources.values()))})
    parent = _under(workspace, 'exports/lesson-content/mastervision-migration/code'); _directory(parent)
    cache = parent / commit
    if cache.exists():
        verify_cache(cache, commit, manifest)
        return cache, commit, _sha(manifest)
    # Keep temporary names short enough for Windows' legacy path limit too.
    stage_prefix = '.stage-' + commit[:8] + '-'
    stage = parent / (stage_prefix + uuid.uuid4().hex[:12])
    stage.mkdir()
    try:
        for name, content in sources.items():
            destination = _under(stage, name); destination.parent.mkdir(parents=True, exist_ok=True)
            fd = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, 'wb') as stream: stream.write(content)
        fd = os.open(stage / MANIFEST, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'wb') as stream: stream.write(manifest)
        verify_cache(stage, commit, manifest)
        try: stage.rename(cache)
        except FileExistsError: verify_cache(cache, commit, manifest)
    finally:
        if stage.exists():
            if stage.resolve().parent != parent.resolve() or _reparse(stage) or not stage.name.startswith(stage_prefix):
                raise LaunchError('unsafe_stage_cleanup')
            shutil.rmtree(stage)
    return cache, commit, _sha(manifest)


def _process_options(workspace, cwd):
    options = {'cwd': str(cwd), 'env': {**os.environ, 'MASTER_VISION_WORKSPACE': str(workspace),
        'PYTHONUTF8': '1', 'PYTHONDONTWRITEBYTECODE': '1'}}
    if os.name == 'nt':
        options['creationflags'] = subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP
    else: options['start_new_session'] = True
    return options


def _write_job(path, job, create=False):
    if create:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'wb') as stream: stream.write(_json(job)); stream.flush(); os.fsync(stream.fileno())
        return
    temporary = path.parent / ('.' + path.name + '-' + uuid.uuid4().hex + '.tmp')
    try:
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'wb') as stream: stream.write(_json(job)); stream.flush(); os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists(): temporary.unlink()


def launch(repo, workspace, arguments, revision='HEAD', process_factory=None):
    arguments, workspace = validate_flags(arguments), _workspace(workspace)
    cache, commit, manifest_sha = prepare_code(repo, workspace, revision)
    jobs = _under(workspace, 'exports/lesson-content/mastervision-migration/jobs'); _directory(jobs)
    ident = 'job-' + uuid.uuid4().hex
    job_file, log_file = jobs / (ident + '.json'), jobs / (ident + '.log')
    job = {'version': 1, 'job_id': ident, 'workspace': str(workspace), 'source_commit': commit,
        'source_manifest_sha256': manifest_sha, 'arguments': arguments, 'status': 'starting',
        'monitor_pid': None, 'pid': None, 'created_at_utc': _now(), 'started_at_utc': None,
        'finished_at_utc': None, 'exit_code': None, 'error': None}
    fd = os.open(log_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600); os.close(fd)
    _write_job(job_file, job, create=True)
    try:
        process = (process_factory or subprocess.Popen)(
            [sys.executable, '-B', str(cache / MONITOR), '--monitor', str(job_file)],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            **_process_options(workspace, cache))
    except Exception:
        job.update(status='failed', finished_at_utc=_now(), error='monitor_start_failed')
        _write_job(job_file, job)
        raise LaunchError('monitor_start_failed') from None
    # Only the monitor updates state after spawn, preventing a parent/child race.
    return {'status': 'started', 'job_id': ident, 'monitor_pid': process.pid,
            'source_commit': commit, 'job_file': str(job_file)}


def _load_job(job_file, workspace):
    jobs = _under(workspace, 'exports/lesson-content/mastervision-migration/jobs')
    path = Path(job_file)
    if (not path.is_absolute() or path.parent != jobs or not re.fullmatch(r'job-[0-9a-f]{32}\.json', path.name)
            or _reparse(path) or not path.is_file() or path.stat().st_size > MAX_META_BYTES):
        raise LaunchError('invalid_job_file')
    try: job = json.loads(path.read_bytes())
    except (ValueError, UnicodeError): raise LaunchError('invalid_job_file') from None
    if (not isinstance(job, dict) or set(job) != JOB_KEYS or job['version'] != 1
            or job['workspace'] != str(workspace) or job['job_id'] != path.stem
            or not isinstance(job['source_commit'], str) or not re.fullmatch('[0-9a-f]{40}', job['source_commit'])
            or not isinstance(job['source_manifest_sha256'], str) or not re.fullmatch('[0-9a-f]{64}', job['source_manifest_sha256'])):
        raise LaunchError('invalid_job_file')
    validate_flags(job['arguments'])
    if (job['status'] != 'starting' or any(job[key] is not None for key in
            ('monitor_pid', 'pid', 'started_at_utc', 'finished_at_utc', 'exit_code', 'error'))):
        raise LaunchError('job_already_started')
    return path, job


def monitor(job_file, *, workspace=None, process_factory=None, current_script=None):
    workspace = _workspace(workspace)
    path, job = _load_job(job_file, workspace)
    child = None
    try:
        cache = _under(workspace, 'exports/lesson-content/mastervision-migration/code/' + job['source_commit'])
        if verify_cache(cache, job['source_commit']) != job['source_manifest_sha256']:
            raise LaunchError('cache_integrity_invalid')
        if Path(current_script or SCRIPT).resolve() != (cache / MONITOR).resolve():
            raise LaunchError('monitor_source_mismatch')
        log_file = path.with_suffix('.log')
        if not log_file.is_file() or _reparse(log_file): raise LaunchError('invalid_job_log')
        with log_file.open('ab', buffering=0) as log:
            child = (process_factory or subprocess.Popen)(
                [sys.executable, '-B', str(cache / ENTRY), *job['arguments']],
                stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
                **_process_options(workspace, cache))
            job.update(status='running', monitor_pid=os.getpid(), pid=child.pid, started_at_utc=_now())
            _write_job(path, job)
            code = child.wait()
            if type(code) is not int: raise LaunchError('worker_exit_unknown')
            job.update(status='completed' if code == 0 else 'failed', exit_code=code, finished_at_utc=_now())
            _write_job(path, job)
            return code
    except Exception as exc:
        if child is not None and child.poll() is None:
            child.terminate()
            try: child.wait(timeout=10)
            except Exception: child.kill(); child.wait(timeout=10)
        code = str(exc) if isinstance(exc, LaunchError) else 'worker_start_or_monitor_failed'
        job.update(status='failed', monitor_pid=os.getpid(), finished_at_utc=_now(), error=code)
        _write_job(path, job)
        return 1


def main(arguments=None):
    try:
        options = parse_arguments(sys.argv[1:] if arguments is None else arguments)
        workspace = _workspace()
        if 'monitor' in options: return monitor(options['monitor'], workspace=workspace)
        result = launch(REPO, workspace, options['arguments'], options['revision'])
        print(json.dumps(result, sort_keys=True), flush=True)
        return 0
    except Exception as exc:
        code = str(exc) if isinstance(exc, LaunchError) else 'launcher_failed'
        print(json.dumps({'status': 'failed', 'code': code}), flush=True)
        return 1


if __name__ == '__main__': raise SystemExit(main())

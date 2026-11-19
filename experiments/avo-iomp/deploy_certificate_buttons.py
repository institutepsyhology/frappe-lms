"""Install the reviewed IOMP certificate-button converter without recreating services."""

import argparse
import ast
import base64
import hashlib
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys


REPO = Path(__file__).resolve().parents[2]
FILE = 'lms/lms/avo_transform.py'
BASELINE = '03f6bb92d5830a30b210e568d85fd9bab2883a8cc00d1e906c5f377bbaf1e28c'
SERVICES = ('backend', 'frontend', 'websocket', 'queue-short', 'queue-long', 'scheduler')

REPLACE = r"""
import hashlib, os, stat, sys, tempfile
from pathlib import Path
path = Path(sys.argv[1])
expected, new = sys.argv[2:]
raw = sys.stdin.buffer.read(300001)
def digest(data):
    return hashlib.sha256(data).hexdigest()
assert path.is_file() and not path.is_symlink() and digest(raw) == new and len(raw) <= 300000
old = path.stat()
fd, tmp = tempfile.mkstemp(dir=path.parent, prefix='.avo-transform-')
try:
    with os.fdopen(fd, 'wb') as stream:
        os.fchown(stream.fileno(), old.st_uid, old.st_gid)
        os.fchmod(stream.fileno(), stat.S_IMODE(old.st_mode))
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    assert digest(path.read_bytes()) == expected
    os.replace(tmp, path)
    assert digest(path.read_bytes()) == new
finally:
    Path(tmp).unlink(missing_ok=True)
"""

# Detect the master by process ancestry; only it receives HUP. The contact
# importer and its parent are independent of Gunicorn's worker process tree.
RELOAD = r"""
import os, signal, sys, time
from pathlib import Path
def processes():
    result = {}
    for item in Path('/proc').glob('[0-9]*'):
        try:
            args = (item / 'cmdline').read_bytes().split(b'\0')
            if not (args[0].strip().startswith(b'gunicorn:') or
                    any(arg.rsplit(b'/', 1)[-1] == b'gunicorn' for arg in args[:2])):
                continue
            fields = (item / 'stat').read_text().rsplit(')', 1)[1].split()
            result[int(item.name)] = (int(fields[1]), int(fields[19]))
        except (FileNotFoundError, ProcessLookupError):
            continue
    return result
initial = processes()
masters = [pid for pid, (parent, _) in initial.items() if parent not in initial]
assert len(masters) == 1
master, = masters
def workers(tree):
    return {(pid, start) for pid, (parent, start) in tree.items() if parent == master}
old = workers(initial)
assert old
if sys.argv[1] == 'signal':
    os.kill(master, signal.SIGHUP)
    deadline = time.monotonic() + 85
    while time.monotonic() < deadline:
        time.sleep(0.5)
        current = processes()
        assert current.get(master) == initial[master]
        children = workers(current)
        if len(children) >= len(old) and children.isdisjoint(old):
            break
    else:
        raise RuntimeError('gunicorn_worker_reload_unverified')
"""


def _server():
    import fcntl
    import os
    import stat
    import tempfile
    import yaml

    config = Path('/opt/company-lms/runtime/compose.yaml')
    overlays = Path('/opt/company-lms/overlays')
    target = '/home/frappe/frappe-bench/apps/lms/' + FILE

    def digest(data):
        return hashlib.sha256(data).hexdigest()

    def run(argv, data=None, timeout=100):
        return subprocess.run(argv, input=data, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                              check=True, timeout=timeout).stdout

    def temporary_write(path, data, mode, owner=None):
        fd, tmp = tempfile.mkstemp(dir=path.parent, prefix='.certificate-buttons-')
        try:
            with os.fdopen(fd, 'wb') as stream:
                if owner:
                    os.fchown(stream.fileno(), *owner)
                os.fchmod(stream.fileno(), mode)
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            return Path(tmp)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise

    def retain(path, raw, mode):
        assert not path.is_symlink()
        if path.exists():
            assert path.is_file() and path.read_bytes() == raw
        else:
            os.replace(temporary_write(path, raw, mode), path)

    request = json.loads(sys.stdin.buffer.read(500001))
    assert set(request) == {'revision', 'sha256', 'data'} and re.fullmatch('[a-f0-9]{40}', request['revision'])
    raw = base64.b64decode(request['data'], validate=True)
    new = digest(raw)
    assert new == request['sha256'] and new != BASELINE and 0 < len(raw) <= 300000
    ast.parse(raw)
    overlays.mkdir(mode=0o700, exist_ok=True)
    assert not overlays.is_symlink() and overlays.is_dir()
    lock_fd = os.open(overlays / '.certificate-buttons.lock', os.O_NOFOLLOW | os.O_CREAT | os.O_WRONLY, 0o600)
    fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    folder = overlays / ('certificate-buttons-' + request['revision'])
    assert not folder.is_symlink()
    folder.mkdir(mode=0o700, exist_ok=True)
    overlay = folder / 'avo_transform.py'
    assert config.is_file() and not config.is_symlink()
    original = config.read_bytes()
    meta = config.stat()
    settings = yaml.safe_load(original)
    binding = str(overlay) + ':' + target + ':ro'
    containers = {}
    before = {}
    needs_binding = []
    for service in SERVICES:
        definition = settings['services'][service]
        volumes = list(definition.get('volumes') or [])
        bindings = [v for v in volumes if v == binding or
                    (v.get('target') if isinstance(v, dict) else (v.split(':') + [None])[1]) == target]
        assert not bindings or bindings == [binding]
        if not bindings:
            needs_binding.append(service)
            definition['volumes'] = volumes + [binding]
        container_name = 'company-lms-' + service + '-1'
        identity = json.loads(run(['docker', 'inspect', container_name]))[0]
        assert identity['State']['Running'] and identity['Config']['Labels']['com.docker.compose.service'] == service
        container = containers[service] = identity['Id']
        mounted = [m for m in identity['Mounts'] if m['Destination'] == target]
        assert not mounted or (len(mounted) == 1 and mounted[0]['Source'] == str(overlay)
                               and not mounted[0]['RW'] and bindings == [binding])
        data = run(['docker', 'exec', container, 'cat', target])
        assert digest(data) in (BASELINE, new)
        if mounted:
            assert digest(data) == new
        before[service] = data
    # Compose is rewritten in one operation, so a mixed initial state is foreign.
    assert len(needs_binding) in (0, len(SERVICES))
    previous = folder / 'avo_transform.before.py'
    baseline = next((data for data in before.values() if digest(data) == BASELINE), None)
    if baseline is None:
        assert previous.is_file() and not previous.is_symlink() and digest(previous.read_bytes()) == BASELINE
    else:
        retain(previous, baseline, 0o600)
    backup = folder / 'compose.before.yaml'
    if needs_binding:
        retain(backup, original, 0o600)
    else:
        assert backup.is_file() and not backup.is_symlink()
    retain(overlay, raw, 0o644)
    updated = yaml.safe_dump(settings, sort_keys=False, allow_unicode=True).encode() if needs_binding else original
    mode = stat.S_IMODE(meta.st_mode)
    owner = meta.st_uid, meta.st_gid
    tmp = temporary_write(config, updated, mode, owner)
    validate = ['docker', 'compose', '--project-directory', str(config.parent), '-f']
    manifest = folder / 'manifest.json'
    report = {'revision': request['revision'], 'sha256': new, 'services': list(SERVICES)}
    manifest_data = json.dumps(report, sort_keys=True).encode()
    reload_needed = before['backend'] != raw or not manifest.exists()
    activated = []
    replaced = signalled = False

    def switch(service, old, new_bytes):
        run(['docker', 'exec', '-i', '-u', 'root', containers[service], 'python', '-c', REPLACE,
             target, digest(old), digest(new_bytes)], new_bytes)

    def gunicorn(action):
        run(['docker', 'exec', '-u', 'root', containers['backend'], 'python', '-c', RELOAD, action])

    try:
        run(validate + [str(tmp), 'config', '--quiet'])
        if reload_needed:
            gunicorn('check')
        if updated != original:
            assert config.read_bytes() == original
            os.replace(tmp, config)
            replaced = True
        for service in SERVICES:
            if before[service] != raw:
                activated.append(service)
                switch(service, before[service], raw)
        for service, cid in containers.items():
            assert run(['docker', 'inspect', '-f', '{{.Id}}', 'company-lms-' + service + '-1']).decode().strip() == cid
            assert run(['docker', 'exec', cid, 'cat', target]) == raw
        assert config.read_bytes() == updated
        if reload_needed:
            signalled = True
            gunicorn('signal')
        retain(manifest, manifest_data, 0o600)
    except BaseException:
        errors = []
        for service in reversed(activated):
            try:
                current = run(['docker', 'exec', containers[service], 'cat', target])
                if current != before[service]:
                    assert current == raw
                    switch(service, raw, before[service])
            except Exception:
                errors.append(service)
        if replaced:
            try:
                assert config.read_bytes() == updated
                os.replace(temporary_write(config, original, mode, owner), config)
            except Exception:
                errors.append('compose')
        if signalled:
            try:
                gunicorn('signal')
            except Exception:
                errors.append('gunicorn')
        if errors:
            raise RuntimeError('rollback_incomplete_' + '_'.join(errors)) from None
        raise
    finally:
        tmp.unlink(missing_ok=True)
    print(json.dumps({**report, 'installed': True, 'reloaded': reload_needed}))


def main():
    import inspect
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--release', required=True)
    revision = parser.parse_args().release
    if not re.fullmatch('[a-f0-9]{40}', revision):
        parser.error('expected a full commit hash')
    data = subprocess.check_output(['git', 'show', revision + ':' + FILE], cwd=REPO)
    digest = hashlib.sha256(data).hexdigest()
    ast.parse(data)
    script = ('import ast,base64,hashlib,json,re,subprocess,sys\nfrom pathlib import Path\n' +
              '\n'.join(f'{key}={globals()[key]!r}' for key in ('FILE','SERVICES','BASELINE','REPLACE','RELOAD')) +
              '\n' + inspect.getsource(_server) + '\n_server()')
    command = [str(Path('C:/Windows/System32/OpenSSH/ssh.exe')), '-o', 'BatchMode=yes',
               '-o', 'StrictHostKeyChecking=yes', '-o', 'ConnectTimeout=15',
               '-o', 'UserKnownHostsFile=' + str(REPO.parent / 'frappe-deploy/known_hosts'),
               '-i', str(Path.home() / '.ssh/codex_timeweb_lms_20261010'), 'root@89.223.71.30',
               shlex.join(['python3', '-c', script])]
    request = {'revision': revision, 'sha256': digest, 'data': base64.b64encode(data).decode('ascii')}
    result = subprocess.run(command, input=json.dumps(request).encode(), capture_output=True, timeout=400)
    if result.returncode:
        last = result.stderr.decode(errors='replace').splitlines()[-1:]
        detail = next((line for line in last if re.fullmatch(r'RuntimeError: rollback_incomplete_[A-Za-z0-9_-]+', line)), '')
        raise SystemExit('certificate_overlay_failed' + (' ' + detail if detail else ''))
    report = json.loads(result.stdout)
    if report.get('revision') != revision or report.get('sha256') != digest or report.get('installed') is not True:
        raise SystemExit('certificate_overlay_unverified')
    print(json.dumps(report))


if __name__ == '__main__':
    main()

"""Guard a frontend-only image release with fresh three-site backups and rollback.

Run on the LMS host as root after bulk writers have stopped. This script does
not change schema, grants, enrollment records, or lesson publication settings.
"""
import argparse
import contextlib
import datetime as dt
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import re
import stat
import subprocess

HERE = Path(__file__).resolve().parent
BASE = Path('/opt/company-lms')
BASELINE = 'sha256:d4a1f221ed802b0625963909334c067d0ba6f164563193519416537e8d9b2d8d'
RELEASE = 'private-course-access-v1'
SITES = ('my-lk.mv-centr.ru', 'my-lk.iomp.ru', 'my-lk.mastervision.su')
MAX_BACKUP_AGE = dt.timedelta(hours=2)
BACKUP_FILES = ('database.sql.gz', 'site-config-before.json', 'site-config-with-key.json')


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def digest(path):
    result = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            result.update(chunk)
    return result.hexdigest()


def private_path(path, directory=False):
    if path.is_symlink():
        raise RuntimeError('backup_symlink_forbidden')
    info = path.stat()
    expected = stat.S_ISDIR if directory else stat.S_ISREG
    if info.st_uid != 0 or info.st_mode & 0o077 or not expected(info.st_mode):
        raise RuntimeError('backup_not_private')
    if not directory and not info.st_size:
        raise RuntimeError('backup_file_empty')


def validate_backup(path, *, base=BASE, now=None, require_latest=True):
    """Read metadata and stream hashes; never emit database/config contents."""
    path, base = Path(path), Path(base)
    root = base / 'backups'
    private_path(root, directory=True)
    if path.name != 'manifest.json' or not re.fullmatch(r'contact-card-\d{8}T\d{12}Z', path.parent.name):
        raise RuntimeError('backup_path_invalid')
    if path.parent.parent.resolve(strict=True) != root.resolve(strict=True):
        raise RuntimeError('backup_outside_root')
    private_path(path.parent, directory=True)
    private_path(path)
    if require_latest:
        manifests = sorted(root.glob('contact-card-*/manifest.json'))
        if not manifests or manifests[-1] != path:
            raise RuntimeError('explicit_backup_is_not_latest')
    report = json.loads(path.read_text(encoding='utf-8'))
    if report.get('directory') != str(path.parent):
        raise RuntimeError('backup_directory_mismatch')
    if report.get('release') != RELEASE or report.get('baseline_image') != BASELINE:
        raise RuntimeError('backup_release_mismatch')
    prepared = dt.datetime.fromisoformat(report['prepared_at_utc'])
    current = now or dt.datetime.now(dt.timezone.utc)
    if prepared.tzinfo is None or current - prepared > MAX_BACKUP_AGE or prepared - current > dt.timedelta(minutes=1):
        raise RuntimeError('backup_not_fresh')
    sites = report.get('sites', [])
    if len(sites) != len(SITES) or {row.get('site') for row in sites} != set(SITES):
        raise RuntimeError('backup_sites_mismatch')
    for row in sites:
        if row.get('gzip_verified') is not True or row.get('key_saved') is not True:
            raise RuntimeError('backup_flags_invalid')
        site_root = path.parent / row['site']
        private_path(site_root, directory=True)
        expected = row.get('files', {})
        if set(expected) != set(BACKUP_FILES):
            raise RuntimeError('backup_file_manifest_invalid')
        for name in BACKUP_FILES:
            file = site_root / name
            private_path(file)
            if file.stat().st_size != expected[name]['bytes'] or digest(file) != expected[name]['sha256']:
                raise RuntimeError('backup_file_changed')
        if (site_root / 'database.sql.gz').stat().st_size != row['database_bytes']:
            raise RuntimeError('backup_database_size_mismatch')
    return report


def prepare():
    module = load('private_course_prepare', HERE.parent / 'avo-credential-profiles-interface/prepare_sites.py')
    module.EXPECTED = BASELINE
    output = io.StringIO()
    with contextlib.redirect_stdout(output):
        module.main()
    report = json.loads(output.getvalue().strip())
    folder = Path(report['directory'])
    # The shared helper has already streamed every SQL gzip through its CRC.
    for row in report['sites']:
        row['files'] = {name: {'bytes': (folder / row['site'] / name).stat().st_size,
                               'sha256': digest(folder / row['site'] / name)} for name in BACKUP_FILES}
    report.update(release=RELEASE, baseline_image=BASELINE,
                  prepared_at_utc=dt.datetime.now(dt.timezone.utc).isoformat())
    manifest = folder / 'manifest.json'
    temp = folder / 'manifest.private-course-access.json'
    fd = os.open(temp, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(fd, 'w', encoding='utf-8') as stream:
        json.dump(report, stream, indent=2)
        stream.write('\n'); stream.flush(); os.fsync(stream.fileno())
    os.replace(temp, manifest)
    validate_backup(manifest)
    print(json.dumps({'backup_manifest': str(manifest), 'sites': list(SITES), 'verified': True}))
    return 0


def clear_site_caches(module):
    code = '''import frappe,json,sys
from frappe import translate
site=sys.argv[1];frappe.init(site=site);frappe.connect();frappe.set_user('Administrator')
try:
 frappe.clear_cache();translate.clear_cache()
 print(json.dumps({'site':site,'cache_cleared':True,'schema_changed':False}))
finally:frappe.destroy()
'''
    return [json.loads(module.run(['docker', 'exec', '-u', 'frappe', '-w', module.BENCH + '/sites',
                                  module.BACKEND, module.BENCH + '/env/bin/python', '-c', code, site],
                                 timeout=180)) for site in SITES]


def activate(image, manifest, source_revision):
    if not re.fullmatch(r'sha256:[0-9a-f]{64}', image) or image == BASELINE:
        raise RuntimeError('candidate_image_invalid')
    if not re.fullmatch(r'[0-9a-f]{40}', source_revision):
        raise RuntimeError('source_revision_invalid')
    module = load('private_course_activate', HERE.parent / 'avo-credential-profiles-interface/deploy.py')
    if os.geteuid() != 0 or module.run(['hostname']) != 'spb-3-vm-t6fa':
        raise RuntimeError('unexpected_host_or_user')
    validate_backup(manifest)
    rows = json.loads(module.run(['docker', 'image', 'inspect', image]))
    if len(rows) != 1 or rows[0]['Id'] != image:
        raise RuntimeError('candidate_image_missing')
    labels = rows[0]['Config'].get('Labels') or {}
    if (labels.get('ru.mvcentr.baseline') != BASELINE or labels.get('ru.mvcentr.release') != RELEASE
            or labels.get('org.opencontainers.image.revision') != source_revision
            or labels.get('org.opencontainers.image.source') != 'https://github.com/institutepsyhology/frappe-lms'):
        raise RuntimeError('candidate_provenance_mismatch')
    # Shared helper rechecks exact baseline, runtime .env, all six service images,
    # site counts and pings, and restores the prior .env/image on any failure.
    module.OLD, module.NEW, module.TAG = BASELINE, image, image
    module.setup_sites = lambda: clear_site_caches(module)
    return module.main()


@contextlib.contextmanager
def release_lock():
    """Serialize these release invocations; other deployment tools must be idle."""
    import fcntl
    path = BASE / '.private-course-access-release.lock'
    flags = os.O_CREAT | os.O_RDWR | getattr(os, 'O_NOFOLLOW', 0)
    fd = os.open(path, flags, 0o600)
    try:
        info = os.fstat(fd)
        if info.st_uid != 0 or info.st_mode & 0o077 or not stat.S_ISREG(info.st_mode):
            raise RuntimeError('release_lock_not_private')
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError('another_private_course_release_running') from None
        yield
    finally:
        os.close(fd)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    commands.add_parser('prepare')
    command = commands.add_parser('activate')
    command.add_argument('image')
    command.add_argument('--backup-manifest', required=True)
    command.add_argument('--source-revision', required=True)
    args = parser.parse_args()
    if (getattr(os, 'geteuid', lambda: -1)() != 0
            or subprocess.check_output(['hostname'], text=True).strip() != 'spb-3-vm-t6fa'):
        raise RuntimeError('unexpected_host_or_user')
    with release_lock():
        return prepare() if args.command == 'prepare' else activate(args.image, args.backup_manifest, args.source_revision)


if __name__ == '__main__':
    raise SystemExit(main())

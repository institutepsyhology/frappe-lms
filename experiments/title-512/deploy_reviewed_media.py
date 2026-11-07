"""Preserve reviewed images and embedded videos with backups and rollback."""
import datetime
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
BASE = Path('/opt/company-lms')
OLD = 'sha256:a3285416f9c50d7256b577352fb4a4a4ef9d5c6610ed144e06859202c9daa127'
BASE_SHA = 'sha256:b90574d3160c04f5d1597a85a30f23cbdeee017607d89729333237d3e6d13486'
BASE_TAG = 'company-lms:flat-verified-20261105'
TAG = 'company-lms:avo-reviewed-media-20261107'
BACKEND = 'company-lms-backend-1'
SITES = ('my-lk.mastervision.su', 'my-lk.iomp.ru', 'my-lk.mv-centr.ru')
BASE_FILES = ('lms/lms/avo_import.py', 'lms/lms/avo_transform.py', 'lms/lms/avo_html_fragment.py')
FILES = BASE_FILES + ('lms/lms/avo_content_schema.py', 'lms/lms/avo_title_schema.py', 'lms/lms/doctype/lms_course/lms_course.py', 'lms/lms/doctype/lms_course/lms_course.json', 'lms/lms/doctype/course_lesson/course_lesson.json')
EXPECTED_LIVE_SCHEMA_FILES = {
    'lms/lms/doctype/lms_course/lms_course.py': '482776ad76bdb83cc1cf11d49c7624302afaf636d5087cad34c4213b17efbc50',
    'lms/lms/doctype/lms_course/lms_course.json': '1b6e73d1f502090cca19494f311e5500ca0f6bc6f0f0c643f77d9b648d04cc47',
    'lms/lms/doctype/course_lesson/course_lesson.json': '7aae440d1dd3d5b7769e839421ba4868717253e304e5c218742f13017085119a',
}
# The previous release was deployed with CRLF endings. These hashes were
# verified against Git commit 9397a92b with LF converted to CRLF, byte for byte.
BASE_HASHES = {
    'lms/lms/avo_import.py': '6a88fefbaebc8a24721135e8ab78aaf84987db3113de09aab34a3bd39a099869',
    'lms/lms/avo_transform.py': 'baf6cc2b22118c5f890365a6fc23a7365b753768b21e4c3ff5f9cd417b5e5f9b',
    'lms/lms/avo_html_fragment.py': '0aa301b2fbde9ecb898b1d7e6e327ad7667c0c525f7596116bcd5174fe7d3bd1',
}
EXPECTED_LIVE_BASE_FILES = {
    'lms/lms/avo_import.py': '889f98a27071d5dcf9f068d2172e10fce86a5f719c5e97443ee0bc26971a8136',
    'lms/lms/avo_transform.py': 'b626d379aac793e877675099b8a45b99d55359bae8664810f6acee9e8f29ccd9',
    'lms/lms/avo_html_fragment.py': '4494f7657a35677339cb2052486c707f7675753802de3c29d596a1790b7fbfb4',
}

BACKUP = r'''
import gzip, hashlib, json, sys
from pathlib import Path
import frappe
from frappe.utils.backups import BackupGenerator
site, stamp = sys.argv[1:]
frappe.init(site=site); frappe.connect()
try:
 if frappe.db.get_single_value('System Settings','encrypt_backup'):
  raise RuntimeError('encrypted backup requires separate verification')
 target = Path('/home/frappe/frappe-bench/sites') / site / 'private' / 'backups' / ('avo-mcp-' + stamp)
 target.mkdir(mode=0o700)
 c = frappe.conf
 backup = BackupGenerator(c.db_name,c.db_user,c.db_password,db_socket=c.db_socket,
  db_host=c.db_host,db_port=c.db_port,db_type=c.db_type,backup_path=str(target),ignore_conf=True)
 backup.get_backup(ignore_files=True,force=True)
 path = Path(backup.backup_path_db)
 config = Path(backup.backup_path_conf)
 if path.parent != target or config.parent != target or not path.is_file() or not config.is_file():
  raise RuntimeError('backup files missing')
 digest = hashlib.sha256()
 with path.open('rb') as f:
  for part in iter(lambda: f.read(1048576), b''): digest.update(part)
 with gzip.open(path,'rb') as f:
  while f.read(1048576): pass
 print('SAFE_BACKUP:' + json.dumps({'site':site,'bytes':path.stat().st_size,'sha256':digest.hexdigest()}))
finally:
 frappe.destroy()
'''

CHECK_RELEASE = r'''
import json, os
os.chdir('/home/frappe/frappe-bench/sites')
import frappe
rows=[]
for site in %r:
 try:
  frappe.init(site=site); frappe.connect()
  rows.append({'site':site,'individual_access_release_enabled':frappe.conf.get('individual_access_release_enabled') is True})
 finally:
  frappe.destroy()
print('RELEASE_STATE:' + json.dumps(rows))
''' % (SITES,)


def command(args, timeout=120):
    result = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
    if result.returncode:
        raise RuntimeError('command_failed_' + args[0])
    return result.stdout.strip()


def release_states():
    out = command(['docker','exec','-u','frappe','-w','/home/frappe/frappe-bench/sites',
        BACKEND,'/home/frappe/frappe-bench/env/bin/python','-c',CHECK_RELEASE],timeout=60)
    rows = [line.removeprefix('RELEASE_STATE:') for line in out.splitlines() if line.startswith('RELEASE_STATE:')]
    if len(rows) != 1:
        raise RuntimeError('release_state_not_confirmed')
    return json.loads(rows[0])


def main():
    if len(sys.argv) != 2 or not re.fullmatch(r'[0-9a-f]{40}', sys.argv[1]):
        raise RuntimeError('expected_full_reviewed_commit')
    commit = sys.argv[1]
    if os.geteuid() != 0 or command(['hostname']) != 'spb-3-vm-t6fa':
        raise RuntimeError('unexpected_host')
    source_hashes = {}
    for name in FILES:
        path = ROOT / name
        if not path.is_file() or path.is_symlink() or path.stat().st_size > 1_000_000:
            raise RuntimeError('invalid_source')
        source_hashes[name] = hashlib.sha256(path.read_bytes()).hexdigest()
    spec = importlib.util.spec_from_file_location('release_helpers', ROOT / 'russian-deploy.py')
    helper = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(helper)
    if not helper.services_healthy(OLD):
        raise RuntimeError('unexpected_runtime_image')
    live_probe = "import hashlib,json,pathlib; p=pathlib.Path('/home/frappe/frappe-bench/apps/lms'); f=" + repr(tuple(EXPECTED_LIVE_SCHEMA_FILES)) + "; print(json.dumps({x:hashlib.sha256((p/x).read_bytes()).hexdigest() for x in f}))"
    live_hashes=json.loads(command(['docker','exec',BACKEND,'/home/frappe/frappe-bench/env/bin/python','-c',live_probe],timeout=60))
    if live_hashes != EXPECTED_LIVE_SCHEMA_FILES:raise RuntimeError('live_schema_source_mismatch')
    live_probe = "import hashlib,json,pathlib; p=pathlib.Path('/home/frappe/frappe-bench/apps/lms'); f=" + repr(BASE_FILES) + "; print(json.dumps({x:hashlib.sha256((p/x).read_bytes()).hexdigest() for x in f}))"
    live_hashes=json.loads(command(['docker','exec',BACKEND,'/home/frappe/frappe-bench/env/bin/python','-c',live_probe],timeout=60))
    if live_hashes != EXPECTED_LIVE_BASE_FILES:raise RuntimeError('live_import_source_mismatch')
    if command(['docker','image','inspect',BASE_TAG,'--format','{{.Id}}']) != BASE_SHA:
        raise RuntimeError('unexpected_base_image')
    image_data = json.loads(command(['docker','image','inspect',BASE_TAG]))
    base_layers = image_data[0]['RootFS']['Layers']
    if len(base_layers) != 1:
        raise RuntimeError('unexpected_base_layers')
    probe = "import hashlib,json,pathlib; p=pathlib.Path('/home/frappe/frappe-bench/apps/lms'); f=" + repr(BASE_FILES) + "; print(json.dumps({x:hashlib.sha256((p/x).read_bytes()).hexdigest() for x in f}))"
    baseline_hashes = json.loads(command(['docker','run','--rm','--network=none','--entrypoint',
        '/home/frappe/frappe-bench/env/bin/python',BASE_TAG,'-c',probe],timeout=90))
    if baseline_hashes != BASE_HASHES:
        raise RuntimeError('baseline_source_mismatch')
    probe = "import hashlib,json,pathlib; p=pathlib.Path('/home/frappe/frappe-bench/apps/lms'); f=" + repr(FILES) + "; print(json.dumps({x:hashlib.sha256((p/x).read_bytes()).hexdigest() for x in f}))"
    env = BASE / 'runtime/.env'
    original = env.read_bytes()
    lines = re.findall(rb'^LMS_IMAGE=(.+)$', original, re.M)
    if len(lines) != 1 or lines[0].strip().decode() != OLD:
        raise RuntimeError('unexpected_runtime_configuration')
    before = helper.snapshot()
    release_before = release_states()
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    backup_dir = BASE / 'backups' / ('avo-mcp-' + stamp)
    backup_dir.mkdir(mode=0o700)
    helper.write_new(backup_dir / 'runtime.env.before', original)
    helper.write_new(backup_dir / 'site-counts.before.json', (json.dumps(before) + '\n').encode())
    report = {'source_commit':commit, 'previous_image':OLD, 'source_sha256':source_hashes,
              'backup_directory':str(backup_dir), 'ok':False}
    switched = False
    try:
        command([sys.executable,str(ROOT/'experiments/title-512/prepare_content_overlay.py')],timeout=30)
        command(['docker','build','--network=none','--pull=false','--tag',TAG,
                 '-f',str(ROOT / 'experiments/title-512/Backend.Containerfile'),str(ROOT)], timeout=600)
        image = command(['docker','image','inspect',TAG,'--format','{{.Id}}'])
        if not re.fullmatch(r'sha256:[0-9a-f]{64}', image) or image == OLD:
            raise RuntimeError('invalid_candidate_image')
        candidate_data = json.loads(command(['docker','image','inspect',image]))[0]
        candidate_layers = candidate_data['RootFS']['Layers']
        if len(candidate_layers) != 2 or candidate_layers[:1] != base_layers:
            raise RuntimeError('unexpected_candidate_layers')
        actual = json.loads(command(['docker','run','--rm','--network=none','--entrypoint',
            '/home/frappe/frappe-bench/env/bin/python',image,'-c',probe],timeout=90))
        if actual != source_hashes:
            raise RuntimeError('candidate_source_mismatch')
        report['image'] = image
        command(['docker','run','--rm','--network=none','--mount',
            'type=bind,src=' + str(ROOT / 'lms/lms') + ',dst=/tmp/avo-mcp-tests,readonly',
            '--entrypoint','/home/frappe/frappe-bench/env/bin/python',image,
            '-m','unittest','discover','-s','/tmp/avo-mcp-tests','-p','test_avo*.py'],timeout=90)
        report['candidate_tests_passed'] = True
        backups = []
        for site in SITES:
            out = command(['docker','exec','-i','-u','frappe','-w','/home/frappe/frappe-bench/sites',
                BACKEND,'/home/frappe/frappe-bench/env/bin/python','-c',BACKUP,site,stamp],timeout=300)
            rows = [line.removeprefix('SAFE_BACKUP:') for line in out.splitlines() if line.startswith('SAFE_BACKUP:')]
            if len(rows) != 1:
                raise RuntimeError('backup_not_confirmed')
            backups.append(json.loads(rows[0]))
        report['database_backups_verified'] = True
        report['database_backups'] = backups
        temp = env.with_name('.env.avo-mcp-' + stamp)
        helper.write_new(temp, re.sub(rb'(?m)^LMS_IMAGE=.+$', ('LMS_IMAGE=' + image).encode(), original))
        os.replace(temp, env)
        switched = True
        helper.up()
        deadline = time.monotonic() + 150
        while not helper.services_healthy(image) or not all(helper.ping(site) for site in SITES):
            if time.monotonic() >= deadline:
                raise RuntimeError('new_image_health_failed')
            time.sleep(3)
        if helper.snapshot() != before or release_states() != release_before:
            raise RuntimeError('site_state_changed')
        report.update(ok=True, counts_and_languages_unchanged=True, release_switches_unchanged=True,
                      application_services_healthy=True)
    except Exception as error:
        report['error'] = type(error).__name__
        if isinstance(error, RuntimeError):
            report['detail'] = str(error)
        if switched:
            try:
                temp = env.with_name('.env.avo-mcp-rollback-' + stamp)
                helper.write_new(temp, original)
                os.replace(temp, env)
                helper.up()
                deadline = time.monotonic() + 150
                while not helper.services_healthy(OLD) or not all(helper.ping(site) for site in SITES):
                    if time.monotonic() >= deadline:
                        raise RuntimeError('rollback_health_failed')
                    time.sleep(3)
                report['rolled_back'] = True
            except Exception:
                report['rolled_back'] = False
    report['completed_at_utc'] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    helper.write_new(backup_dir / 'result.json', (json.dumps(report,ensure_ascii=False,indent=2)+'\n').encode())
    print(json.dumps(report,ensure_ascii=False))
    return 0 if report['ok'] else 1


if __name__ == '__main__':
    raise SystemExit(main())

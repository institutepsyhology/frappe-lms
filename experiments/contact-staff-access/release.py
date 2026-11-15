"""Pinned one-layer release with fresh backups, additive schema and rollback."""
import importlib.util
import json
from pathlib import Path
import re
import subprocess
import sys

HERE = Path(__file__).resolve().parent
BASE50 = 'sha256:262aa41e480e5c8fa33e0860523a586e9e5af283c59573cf66476dd85374b775'
ACTIVE = 'sha256:ea355d6036b6052827a36eb882ee5b0c5b27194102badb52a5c66cdce9ac391f'
RELEASE = 'contact-staff-access-v1'


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
    return mod


def image(name):
    rows = json.loads(subprocess.check_output(['docker', 'image', 'inspect', name], text=True))
    if len(rows) != 1:
        raise RuntimeError('image_identity_invalid')
    return rows[0]


def setup_sites(module):
    code = '''import frappe,json,runpy,sys
frappe.init(site=sys.argv[1]);frappe.connect();frappe.set_user('Administrator')
try:
 result=runpy.run_path('/home/frappe/frappe-bench/apps/lms/experiments/contact-staff-access/schema.py')['apply_schema']()
 print(json.dumps(result))
finally:frappe.destroy()
'''
    return [json.loads(module.run(['docker', 'exec', '-u', 'frappe', '-w', module.BENCH + '/sites',
                                  module.BACKEND, module.BENCH + '/env/bin/python', '-B', '-c', code, site],
                                 timeout=240)) for site in module.SITES]


def main():
    shared = load('staff_shared_release', HERE.parent / 'private-course-access/release.py')
    shared.BASELINE, shared.RELEASE = ACTIVE, RELEASE
    if len(sys.argv) == 2 and sys.argv[1] == 'prepare':
        # The older backup helper can create absent keys; this release must never
        # invoke that path. Verify all existing keys without emitting any value.
        code = '''import frappe,json
for site in %r:
 frappe.init(site=site)
 try:
  if not frappe.conf.get('encryption_key'):raise RuntimeError('existing_key_missing')
 finally:frappe.destroy()
print('existing_keys_verified')''' % (shared.SITES,)
        subprocess.check_output(['docker','exec','-u','frappe','-w','/home/frappe/frappe-bench/sites',
            'company-lms-backend-1','/home/frappe/frappe-bench/env/bin/python','-B','-c',code])
        with shared.release_lock():
            return shared.prepare()
    if len(sys.argv) != 5 or sys.argv[1] != 'activate':
        raise SystemExit('usage: release.py prepare | activate IMAGE BACKUP_MANIFEST REVISION')
    candidate, backup, revision = sys.argv[2:]
    if not re.fullmatch(r'sha256:[0-9a-f]{64}', candidate) or not re.fullmatch(r'[a-f0-9]{40}', revision):
        raise RuntimeError('invalid_candidate_identity')
    base, result = image(BASE50), image(candidate)
    if result['Id'] != candidate or len(base['RootFS']['Layers']) != 50:
        raise RuntimeError('base_image_invalid')
    if len(result['RootFS']['Layers']) != 51 or result['RootFS']['Layers'][:50] != base['RootFS']['Layers']:
        raise RuntimeError('candidate_layer_mismatch')
    context = Path('/opt/company-lms/private/contact-staff-access-' + revision[:8])
    report = json.loads((context / 'manifest.json').read_text())
    if report.get('revision') != revision or report.get('base') != BASE50:
        raise RuntimeError('source_manifest_mismatch')
    code = ('import hashlib,json,pathlib;p=pathlib.Path("/home/frappe/frappe-bench/apps/lms");'
            'print(json.dumps({n:hashlib.sha256((p/n).read_bytes()).hexdigest() for n in ' + repr(tuple(report['files'])) + '}))')
    actual = json.loads(subprocess.check_output(['docker','run','--rm','--network=none','--read-only',
        '--entrypoint','/home/frappe/frappe-bench/env/bin/python',candidate,'-B','-c',code],text=True))
    if actual != report['files']:
        raise RuntimeError('candidate_source_mismatch')
    shared.clear_site_caches = setup_sites
    with shared.release_lock():
        return shared.activate(candidate, backup, revision)


if __name__ == '__main__':
    raise SystemExit(main())

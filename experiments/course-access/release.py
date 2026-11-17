"""Activate a verified source revision using existing backup/rollback guards."""
import importlib.util
import json
from pathlib import Path
import re
import subprocess
import sys

HERE = Path(__file__).resolve().parent
BASE = 'sha256:8a7e5a581ebe740fc1767aba07ddbed5c88a2be36e4ac93cf8c58467b5d3227c'


def load(name, path):
    spec=importlib.util.spec_from_file_location(name,path)
    module=importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


def schema(module):
    code = '''import frappe,json,runpy,sys
frappe.init(site=sys.argv[1]);frappe.connect();frappe.set_user('Administrator')
try:
 if not frappe.conf.get('encryption_key'):raise RuntimeError('existing_key_required')
 result=runpy.run_path('/home/frappe/frappe-bench/apps/lms/experiments/course-access/schema.py')['apply_schema']()
 print(json.dumps({'site':sys.argv[1],**result}))
finally:frappe.destroy()
'''
    return [json.loads(module.run(['docker','exec','-u','frappe','-w',module.BENCH+'/sites',module.BACKEND,
        module.BENCH+'/env/bin/python','-B','-c',code,site],timeout=180)) for site in module.SITES]


def main():
    shared=load('course_access_shared_release',HERE.parent/'private-course-access/release.py')
    shared.BASELINE,shared.RELEASE=BASE,'course-access-v1'
    if len(sys.argv)==2 and sys.argv[1]=='prepare':
        code='import frappe;sites='+repr(shared.SITES)+'\nfor site in sites:\n frappe.init(site=site)\n assert frappe.conf.get("encryption_key"),"existing_key_required"\n frappe.destroy()'
        subprocess.check_output(['docker','exec','-u','frappe','-w','/home/frappe/frappe-bench/sites',
            'company-lms-backend-1','/home/frappe/frappe-bench/env/bin/python','-B','-c',code])
        with shared.release_lock():return shared.prepare()
    if len(sys.argv)!=6 or sys.argv[1]!='activate':
        raise SystemExit('release.py prepare | activate IMAGE BACKUP_MANIFEST REVISION CONTEXT')
    image,backup,revision,context=sys.argv[2:]
    if not re.fullmatch('[a-f0-9]{40}',revision):raise RuntimeError('invalid_revision')
    manifest=json.loads((Path(context)/'manifest.json').read_text())
    if manifest['revision']!=revision or manifest['base']!=BASE:raise RuntimeError('manifest_mismatch')
    # Source and baseline are checked before touching runtime configuration.
    code='import hashlib,json,pathlib;p=pathlib.Path("/home/frappe/frappe-bench/apps/lms");names='+repr(list(manifest['files']))+';print(json.dumps({n:hashlib.sha256((p/n).read_bytes().replace(b"\\r\\n",b"\\n")).hexdigest() if (p/n).is_file() else None for n in names}))'
    actual=json.loads(subprocess.check_output(['docker','run','--rm','--network=none','--entrypoint','python',image,'-c',code]))
    if actual!=manifest['files']:raise RuntimeError('candidate_source_mismatch')
    # Verify every live application source file this release replaces. Tests and
    # release-only helpers do not execute in the old production runtime.
    live=json.loads(subprocess.check_output(['docker','exec','company-lms-backend-1','python','-c',code]))
    for name,digest in live.items():
        if name.startswith('lms/') and '/test_' not in name and digest not in (manifest['previous'][name],manifest['files'][name]):
            raise RuntimeError('live_source_changed:'+name)
    shared.clear_site_caches=schema
    with shared.release_lock():return shared.activate(image,backup,revision)


if __name__=='__main__':raise SystemExit(main())

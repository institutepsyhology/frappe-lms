"""Guard a backend-only patch; preserve the pinned frontend and rollback image."""
import importlib.util
import json
from pathlib import Path
import re
import subprocess
import sys

HERE = Path(__file__).resolve().parent
BASE50 = 'sha256:262aa41e480e5c8fa33e0860523a586e9e5af283c59573cf66476dd85374b775'
ACTIVE = 'sha256:1593e8f40756f5f383ce71a5344adb84da5b12a00c4cea20ea43bb45ede81008'
RELEASE = 'system-admin-position-v1'


def load(name,path):
    spec=importlib.util.spec_from_file_location(name,path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module


def image(name):
    return json.loads(subprocess.check_output(['docker','image','inspect',name],text=True))[0]


def main():
    shared=load('legacy_role_release',HERE.parent/'private-course-access/release.py')
    shared.BASELINE,shared.RELEASE=ACTIVE,RELEASE
    if len(sys.argv)==2 and sys.argv[1]=='prepare':
        # Reuse the pre-existing-key guard from the tested staff release.
        guarded=load('legacy_role_prepare',HERE.parent/'contact-staff-access/release.py')
        guarded.ACTIVE,guarded.RELEASE=ACTIVE,RELEASE
        return guarded.main()
    if len(sys.argv)!=5 or sys.argv[1]!='activate':
        raise SystemExit('usage: release.py prepare | activate IMAGE BACKUP_MANIFEST REVISION')
    candidate,backup,revision=sys.argv[2:]
    if not re.fullmatch(r'sha256:[a-f0-9]{64}',candidate) or not re.fullmatch(r'[a-f0-9]{40}',revision):
        raise RuntimeError('invalid_candidate_identity')
    baseline,result=image(BASE50),image(candidate)
    if len(result['RootFS']['Layers'])!=51 or result['RootFS']['Layers'][:50]!=baseline['RootFS']['Layers']:
        raise RuntimeError('candidate_layer_mismatch')
    context=Path('/opt/company-lms/private/legacy-credential-role-'+revision[:8])
    manifest=json.loads((context/'manifest.json').read_text())
    if manifest.get('revision')!=revision or manifest.get('base')!=BASE50:
        raise RuntimeError('source_manifest_mismatch')
    code=('import hashlib,json,pathlib;p=pathlib.Path("/home/frappe/frappe-bench/apps/lms");'
          'print(json.dumps({n:hashlib.sha256((p/n).read_bytes()).hexdigest() for n in '+repr(tuple(manifest['files']))+'}))')
    args=['docker','run','--rm','--network=none','--read-only','--entrypoint','/home/frappe/frappe-bench/env/bin/python']
    actual=json.loads(subprocess.check_output([*args,candidate,'-B','-c',code],text=True))
    if actual!=manifest['files']:
        raise RuntimeError('source_hash_mismatch')
    code='''import hashlib,json,pathlib
p=pathlib.Path('/home/frappe/frappe-bench/apps/lms/lms')
names=sorted(x for x in (p/'public/frontend').rglob('*') if x.is_file())+[p/'www/_lms.html']
print(json.dumps({str(x.relative_to(p)):hashlib.sha256(x.read_bytes()).hexdigest() for x in names}))'''
    old=json.loads(subprocess.check_output([*args,ACTIVE,'-B','-c',code],text=True))
    new=json.loads(subprocess.check_output([*args,candidate,'-B','-c',code],text=True))
    if old!=new:
        raise RuntimeError('compiled_frontend_changed')
    with shared.release_lock():
        return shared.activate(candidate,backup,revision)


if __name__=='__main__':
    raise SystemExit(main())

"""Back up and activate an independently tested numeric-user-routes image."""
import importlib.util
import json
from pathlib import Path
import re
import subprocess
import sys

HERE = Path(__file__).resolve().parent
BASE50 = 'sha256:262aa41e480e5c8fa33e0860523a586e9e5af283c59573cf66476dd85374b775'
ACTIVE = 'sha256:49c3f96248bf312703eddc286726009f77233aee7939e685a2a94ff2c90c3702'
RELEASE = 'avo-user-routes-v1'

def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
    return mod

def image(name):
    rows=json.loads(subprocess.check_output(['docker','image','inspect',name],text=True))
    if len(rows)!=1: raise RuntimeError('image_identity_invalid')
    return rows[0]

def main():
    shared=load('user_routes_shared',HERE.parent/'private-course-access/release.py')
    shared.BASELINE=ACTIVE; shared.RELEASE=RELEASE
    if len(sys.argv)==2 and sys.argv[1]=='prepare':
        with shared.release_lock(): return shared.prepare()
    if len(sys.argv)!=5 or sys.argv[1]!='activate':
        raise SystemExit('usage: release.py prepare | activate IMAGE MANIFEST REVISION')
    candidate, manifest, revision=sys.argv[2:]
    if not re.fullmatch(r'sha256:[0-9a-f]{64}',candidate): raise RuntimeError('invalid_image')
    base=image(BASE50); result=image(candidate)
    if result['Id'] != candidate or len(base['RootFS']['Layers']) != 50:
        raise RuntimeError('base_image_invalid')
    layers=result['RootFS']['Layers']
    if len(layers)!=51 or layers[:50]!=base['RootFS']['Layers']:
        raise RuntimeError('candidate_layer_mismatch')
    context=Path('/opt/company-lms/private/avo-user-routes-'+revision[:8])
    report=json.loads((context/'manifest.json').read_text())
    if report.get('revision')!=revision or report.get('base')!=BASE50:
        raise RuntimeError('source_manifest_mismatch')
    names=tuple(report['files'])
    code=('import hashlib,json,pathlib;p=pathlib.Path("/home/frappe/frappe-bench/apps/lms");'
          'print(json.dumps({n:hashlib.sha256((p/n).read_bytes()).hexdigest() for n in '+repr(names)+'}))')
    actual=json.loads(subprocess.check_output(['docker','run','--rm','--network=none','--read-only',
        '--entrypoint','/home/frappe/frappe-bench/env/bin/python',candidate,'-B','-c',code],text=True))
    if actual!=report['files']: raise RuntimeError('candidate_source_mismatch')
    with shared.release_lock(): return shared.activate(candidate,manifest,revision)

if __name__=='__main__': raise SystemExit(main())

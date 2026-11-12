"""Run guarded backups and activation for retrying an overloaded queue."""
import importlib.util
from pathlib import Path
import re
import sys

HERE=Path(__file__).resolve().parent
OLD='sha256:3f6d1884e2dee5dff756a44376214080f89f2e545f24cb8ec1efd878e01d402b'
TAG='company-lms:avo-queue-retry-20261112'
def load(name,path):
    spec=importlib.util.spec_from_file_location(name,path);module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module);return module
def main():
    if len(sys.argv)==2 and sys.argv[1]=='prepare':
        mod=load('prepare_sites',HERE.parent/'avo-credential-profiles-interface/prepare_sites.py')
        mod.EXPECTED=OLD;mod.main();return 0
    if len(sys.argv)==3 and sys.argv[1]=='activate' and re.fullmatch(r'sha256:[0-9a-f]{64}',sys.argv[2]):
        mod=load('guarded_release',HERE.parent/'avo-credential-profiles-interface/deploy.py')
        mod.OLD,mod.NEW,mod.TAG=OLD,sys.argv[2],TAG;return mod.main()
    raise SystemExit('usage: release.py prepare | activate sha256:...')
if __name__=='__main__':raise SystemExit(main())

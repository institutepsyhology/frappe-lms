"""Run verified backups and guarded activation for AVO course URLs."""
import importlib.util
from pathlib import Path
import re
import sys

HERE=Path(__file__).resolve().parent
OLD='sha256:4c1e2fe27bf2212b39504792f989024e1051e0015761ca5672531018e62728dc'
TAG='company-lms:avo-course-urls-20261112'
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

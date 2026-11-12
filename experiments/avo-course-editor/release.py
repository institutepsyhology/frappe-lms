"""Run verified backups and guarded activation for AVO editor URLs."""
import importlib.util
from pathlib import Path
import re,sys
HERE=Path(__file__).resolve().parent
OLD='sha256:687cb6952613928285195f8726b8934a98c51b2b7385a1997987e4e8ddd7e63c'
TAG='company-lms:avo-course-editor-20261112'
def load(name,path):
 spec=importlib.util.spec_from_file_location(name,path);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module
def main():
 if len(sys.argv)==2 and sys.argv[1]=='prepare':
  mod=load('prepare_sites',HERE.parent/'avo-credential-profiles-interface/prepare_sites.py');mod.EXPECTED=OLD;mod.main();return 0
 if len(sys.argv)==3 and sys.argv[1]=='activate' and re.fullmatch(r'sha256:[0-9a-f]{64}',sys.argv[2]):
  mod=load('guarded_release',HERE.parent/'avo-credential-profiles-interface/deploy.py');mod.OLD,mod.NEW,mod.TAG=OLD,sys.argv[2],TAG;return mod.main()
 raise SystemExit('usage: release.py prepare | activate sha256:...')
if __name__=='__main__':raise SystemExit(main())

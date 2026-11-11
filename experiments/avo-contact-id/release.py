"""Back up and activate a tested contact-ID image using the guarded release.

On the LMS host run `prepare` first; pause contact import workers safely before
`activate`. The candidate image ID must be supplied explicitly. The underlying
release verifies services, counts and site health and rolls back on failure.
"""
import importlib.util
from pathlib import Path
import re
import sys

HERE = Path(__file__).resolve().parent
OLD = 'sha256:0a0344aa29de64cee4d02ae9e848dd98bf4b915be6284f639a630fa1111e7b8a'
TAG = 'company-lms:contact-id-55c646fa'

def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

def main():
    if len(sys.argv) == 2 and sys.argv[1] == 'prepare':
        mod = load('prepare_sites', HERE.parent / 'avo-credential-profiles-interface/prepare_sites.py')
        mod.EXPECTED = OLD
        mod.main()
        return 0
    if len(sys.argv) == 3 and sys.argv[1] == 'activate' and re.fullmatch(r'sha256:[0-9a-f]{64}', sys.argv[2]):
        mod = load('guarded_release', HERE.parent / 'avo-credential-profiles-interface/deploy.py')
        mod.OLD, mod.NEW, mod.TAG = OLD, sys.argv[2], TAG
        return mod.main()
    raise SystemExit('usage: release.py prepare | activate sha256:...')

if __name__ == '__main__': raise SystemExit(main())

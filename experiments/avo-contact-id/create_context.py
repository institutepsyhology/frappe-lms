"""Create a minimal release context from the committed, reviewed sources."""
import hashlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tarfile

ROOT = Path(__file__).resolve().parents[2]
FILES = ['lms/lms/api.py', 'lms/lms/avo_contact_card.py', 'lms/lms/test_avo_contact_resolver_unit.py',
         'frontend/src/routes.js', 'frontend/src/components/Settings/Members.vue',
         'frontend/src/components/Settings/AvoContactCard.vue', 'frontend/src/pages/Forms/AvoContactById.vue',
         'frontend/src/tests/avoContactById.test.ts']

def main():
    out = Path(sys.argv[1]).resolve()
    out.mkdir(parents=True, exist_ok=False)
    commit = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
    hashes = {}
    with tarfile.open(out / 'overlay.tar', 'w') as tar:
        for name in FILES:
            data = subprocess.check_output(['git', 'show', f'{commit}:{name}'], cwd=ROOT).replace(b'\r\n', b'\n')
            hashes[name] = hashlib.sha256(data).hexdigest()
            info = tarfile.TarInfo(name); info.size = len(data); info.mode = 0o644; info.mtime = 0
            tar.addfile(info, io.BytesIO(data))
    (out / 'Dockerfile').write_bytes((ROOT / 'experiments/avo-contact-id/Dockerfile').read_bytes().replace(b'\r\n', b'\n'))
    (out / 'manifest.json').write_text(json.dumps({'commit': commit, 'sha256': hashes}, indent=2), encoding='utf-8')
    print(json.dumps({'commit': commit, 'files': len(FILES)}))

if __name__ == '__main__': main()

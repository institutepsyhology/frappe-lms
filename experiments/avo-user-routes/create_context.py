"""Build a pinned, single-layer release context for numeric user routes."""
import hashlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tarfile

ROOT = Path(__file__).resolve().parents[2]
BASE = 'sha256:262aa41e480e5c8fa33e0860523a586e9e5af283c59573cf66476dd85374b775'
FILES = (
    'lms/lms/avo_html_fragment.py', 'lms/lms/avo_transform.py',
    'lms/lms/test_avo_reviewed_embed_html.py',
    'lms/lms/avo_user_routes.py', 'lms/lms/test_avo_user_routes_unit.py',
    'frontend/src/components/Settings/Members.vue', 'frontend/src/pages/Forms/AvoContactById.vue',
    'frontend/src/pages/Forms/ProfileEditForm.vue', 'frontend/src/pages/Profile.vue',
    'frontend/src/tests/avoContactById.test.ts', 'frontend/src/tests/profileEditRoute.test.ts',
)

def main():
    out = Path(sys.argv[1]).resolve()
    if out.exists() or out.is_relative_to(ROOT): raise ValueError('invalid_context_directory')
    revision = subprocess.check_output(['git','rev-parse','HEAD'], cwd=ROOT, text=True).strip()
    files = {name: subprocess.check_output(['git','show',revision+':'+name],cwd=ROOT).replace(b'\r\n',b'\n') for name in FILES}
    hashes = {name:hashlib.sha256(data).hexdigest() for name,data in files.items()}
    out.mkdir()
    with tarfile.open(out/'overlay.tar','w') as tar:
        for name,data in files.items():
            info=tarfile.TarInfo(name);info.size=len(data);info.mode=0o644;info.mtime=0
            tar.addfile(info,io.BytesIO(data))
    recipe=f'''# syntax=docker/dockerfile:1.4
FROM company-lms:avo-user-routes-base50
USER root
WORKDIR /home/frappe/frappe-bench
RUN --mount=type=bind,source=overlay.tar,target=/tmp/overlay.tar \\
    tar -xf /tmp/overlay.tar -C apps/lms && tar -tf /tmp/overlay.tar | sed 's|^|apps/lms/|' | xargs chown frappe:0 && \\
    su -s /bin/sh frappe -c 'env/bin/python -B -m unittest lms.lms.test_avo_user_routes_unit lms.lms.test_avo_import_unit lms.lms.test_avo_reviewed_embed_html -q && cd apps/lms/frontend && node node_modules/vitest/vitest.mjs run --maxWorkers=1 src/tests/avoContactById.test.ts src/tests/profileEditRoute.test.ts src/tests/memberFormRoute.test.ts && NODE_OPTIONS=--max-old-space-size=1600 yarn build'
LABEL org.opencontainers.image.source="https://github.com/institutepsyhology/frappe-lms" org.opencontainers.image.revision="{revision}"
'''
    (out/'Dockerfile').write_text(recipe,encoding='utf8',newline='\n')
    (out/'manifest.json').write_text(json.dumps({'revision':revision,'base':BASE,'files':hashes},indent=2),encoding='utf8')
    print(json.dumps({'revision':revision,'file_count':len(files)}))

if __name__ == '__main__': main()

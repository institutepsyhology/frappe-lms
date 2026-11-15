"""Backend-only, single-layer release reusing the verified frontend verbatim."""
import hashlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tarfile

ROOT = Path(__file__).resolve().parents[2]
BASE = 'sha256:262aa41e480e5c8fa33e0860523a586e9e5af283c59573cf66476dd85374b775'
ACTIVE = 'sha256:1593e8f40756f5f383ce71a5344adb84da5b12a00c4cea20ea43bb45ede81008'
FRONTEND_REVISION = '90cbdd59881490c4cb659987133bf474b50cd444'


def source(revision, name):
    return subprocess.check_output(['git','show',revision+':'+name],cwd=ROOT).replace(b'\r\n',b'\n')


def main():
    out = Path(sys.argv[1]).resolve()
    if out.exists() or out.is_relative_to(ROOT):
        raise ValueError('invalid_context_directory')
    revision = subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()
    names = json.loads(source(revision,'experiments/contact-staff-access/source_paths.json'))
    names += ['experiments/legacy-credential-role/'+name for name in ('create_context.py','release.py','smoke.py','README.md')]
    files = {name:source(revision,name) for name in names}
    # Copying compiled assets is allowed only when their committed source is
    # identical to the already tested production frontend.
    for name,data in files.items():
        if name.startswith('frontend/') and data != source(FRONTEND_REVISION,name):
            raise RuntimeError('frontend_changed_requires_rebuild')
    out.mkdir()
    with tarfile.open(out/'overlay.tar','w') as tar:
        for name,data in files.items():
            info=tarfile.TarInfo(name);info.size=len(data);info.mode=0o644;info.mtime=0
            tar.addfile(info,io.BytesIO(data))
    tests=' '.join('lms.lms.'+name for name in (
        'test_staff_authority_unit','test_staff_positions_unit','test_staff_access_permissions_unit',
        'test_access_blocks_unit','test_access_provenance_unit','test_avo_user_routes_unit',
        'test_contact_workspace_unit','test_avo_contact_resolver_unit','test_course_people_unit',
        'test_credential_profiles_unit','test_avo_import_unit','test_avo_reviewed_embed_html'))
    recipe=f'''# syntax=docker/dockerfile:1.4
FROM company-lms:legacy-credential-role-722522d1 AS compiled
FROM company-lms:avo-user-routes-base50
USER root
RUN --mount=type=bind,source=overlay.tar,target=/tmp/overlay.tar \\
    --mount=type=bind,from=compiled,source=/home/frappe/frappe-bench/apps/lms/lms/public/frontend,target=/tmp/compiled \\
    --mount=type=bind,from=compiled,source=/home/frappe/frappe-bench/apps/lms/lms/www/_lms.html,target=/tmp/_lms.html \\
    tar -xf /tmp/overlay.tar -C apps/lms && tar -tf /tmp/overlay.tar | sed 's|^|apps/lms/|' | xargs chown frappe:0 && \\
    rm -rf apps/lms/lms/public/frontend && mkdir -p apps/lms/lms/public/frontend && \\
    cp -a /tmp/compiled/. apps/lms/lms/public/frontend/ && cp /tmp/_lms.html apps/lms/lms/www/_lms.html && \\
    chown -R frappe:0 apps/lms/lms/public/frontend apps/lms/lms/www/_lms.html && \\
    su -s /bin/sh frappe -c 'env/bin/python -B -m unittest {tests} -q'
USER frappe
LABEL org.opencontainers.image.source="https://github.com/institutepsyhology/frappe-lms" org.opencontainers.image.revision="{revision}" ru.mvcentr.baseline="{ACTIVE}" ru.mvcentr.release="system-admin-position-v1"
'''
    (out/'Dockerfile').write_text(recipe,encoding='utf8',newline='\n')
    (out/'manifest.json').write_text(json.dumps({'revision':revision,'base':BASE,'frontend_revision':FRONTEND_REVISION,
        'files':{name:hashlib.sha256(data).hexdigest() for name,data in files.items()}},indent=2),encoding='utf8')
    print(json.dumps({'revision':revision,'files':len(files),'frontend_unchanged':True}))


if __name__=='__main__':
    main()

"""Create a reproducible cumulative overlay from an exact published revision."""
import hashlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tarfile

ROOT = Path(__file__).resolve().parents[2]
BASE = 'sha256:262aa41e480e5c8fa33e0860523a586e9e5af283c59573cf66476dd85374b775'
ACTIVE = 'sha256:ea355d6036b6052827a36eb882ee5b0c5b27194102badb52a5c66cdce9ac391f'


def main():
    out = Path(sys.argv[1]).resolve()
    if out.exists() or out.is_relative_to(ROOT):
        raise ValueError('invalid_context_directory')
    revision = subprocess.check_output(['git','rev-parse','HEAD'], cwd=ROOT, text=True).strip()
    names = json.loads(subprocess.check_output(['git','show',revision+':experiments/contact-staff-access/source_paths.json'],cwd=ROOT))
    files = {name:subprocess.check_output(['git','show',revision+':'+name],cwd=ROOT).replace(b'\r\n',b'\n') for name in names}
    out.mkdir()
    with tarfile.open(out/'overlay.tar','w') as tar:
        for name,data in files.items():
            info=tarfile.TarInfo(name);info.size=len(data);info.mode=0o644;info.mtime=0
            tar.addfile(info,io.BytesIO(data))
    pytests = ' '.join('lms.lms.'+name for name in (
        'test_staff_authority_unit','test_staff_positions_unit','test_staff_access_permissions_unit',
        'test_access_blocks_unit','test_access_provenance_unit','test_avo_user_routes_unit',
        'test_contact_workspace_unit','test_avo_contact_resolver_unit','test_course_people_unit',
        'test_credential_profiles_unit','test_avo_import_unit','test_avo_reviewed_embed_html'))
    uitests = ' '.join('src/tests/'+name+'.test.ts' for name in (
        'avoContactById','avoContactCard','memberFormRoute','membersSearch','profileEditRoute',
        'individualAccessSettings','coursePeopleDashboard','personCourseAccessDialog','staffMatrix',
        'settingsAccess','mobileSettings','courseMemberVisibility','credentialProfiles'))
    recipe=f'''# syntax=docker/dockerfile:1.4
FROM company-lms:avo-user-routes-base50
USER root
RUN --mount=type=bind,source=overlay.tar,target=/tmp/overlay.tar \\
    tar -xf /tmp/overlay.tar -C apps/lms && tar -tf /tmp/overlay.tar | sed 's|^|apps/lms/|' | xargs chown frappe:0 && \\
    su -s /bin/sh frappe -c 'ulimit -c 0; env/bin/python -B -m unittest {pytests} -q && cd apps/lms/frontend && node node_modules/vitest/vitest.mjs run --maxWorkers=1 {uitests} && NODE_OPTIONS=--max-old-space-size=2100 nice -n 15 yarn build'
USER frappe
LABEL org.opencontainers.image.source="https://github.com/institutepsyhology/frappe-lms" org.opencontainers.image.revision="{revision}" ru.mvcentr.baseline="{ACTIVE}" ru.mvcentr.release="contact-staff-access-v1"
'''
    (out/'Dockerfile').write_text(recipe,encoding='utf8',newline='\n')
    (out/'manifest.json').write_text(json.dumps({'revision':revision,'base':BASE,
        'files':{name:hashlib.sha256(data).hexdigest() for name,data in files.items()}},indent=2),encoding='utf8')
    print(json.dumps({'revision':revision,'files':len(files)}))


if __name__=='__main__':
    main()

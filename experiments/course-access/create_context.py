"""Build a pinned, reproducible delta from an exact committed revision."""
import hashlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tarfile

ROOT = Path(__file__).resolve().parents[2]
BASE = 'sha256:8a7e5a581ebe740fc1767aba07ddbed5c88a2be36e4ac93cf8c58467b5d3227c'
BASE_TAG = 'company-lms:legacy-credential-role-b2793377'
IMAGE_REVISION = 'b279337761b7751265dfdf893d95009de0c514ad'
SOURCE_BASE = 'ee3ae23f'
PYTESTS = ('test_course_people_unit', 'test_contact_workspace_unit', 'test_visit_tracking_unit',
           'test_access_blocks_unit', 'test_access_presentation_unit', 'test_avo_course_routes_unit')
UITESTS = ('personCourseAccessDialog', 'avoContactCard', 'coursePeopleDashboard', 'lessonLocking',
           'scormChapterLocking', 'individualAccessSettings', 'accessNotice', 'unavailableAccessSettings',
           'lessonAccessSettings', 'coursePublishSettings', 'ChapterRow', 'studentLessonSidebar')


def git(*args):
    return subprocess.check_output(['git', *args], cwd=ROOT)


def main():
    target = Path(sys.argv[1]).resolve()
    if target.exists() or target.is_relative_to(ROOT):
        raise ValueError('new_context_outside_checkout_required')
    revision = git('rev-parse', 'HEAD').decode().strip()
    candidates = git('diff', '--name-only', IMAGE_REVISION, revision).decode().splitlines()
    names = [n for n in candidates if n.startswith(('lms/', 'frontend/', 'experiments/course-access/'))
             or n == 'experiments/contact-staff-access/smoke_roster.py']
    files = {n: git('show', revision+':'+n).replace(b'\r\n', b'\n') for n in names}
    previous = {}
    for name in names:
        p = subprocess.run(['git', 'show', SOURCE_BASE+':'+name], cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        previous[name] = hashlib.sha256(p.stdout.replace(b'\r\n', b'\n')).hexdigest() if p.returncode == 0 else None
    target.mkdir()
    with tarfile.open(target/'overlay.tar', 'w') as archive:
        for name, raw in files.items():
            item = tarfile.TarInfo(name); item.size = len(raw); item.mode = 0o644; item.mtime = 0
            archive.addfile(item, io.BytesIO(raw))
    pytests = ' '.join('lms.lms.'+n for n in PYTESTS)
    uitests = ' '.join('src/tests/'+n+'.test.ts' for n in UITESTS)
    recipe = f'''# syntax=docker/dockerfile:1.4
FROM {BASE_TAG}
USER root
RUN --mount=type=bind,source=overlay.tar,target=/tmp/overlay.tar tar -xf /tmp/overlay.tar -C apps/lms && tar -tf /tmp/overlay.tar | sed 's|^|apps/lms/|' | xargs chown frappe:0 && su -s /bin/sh frappe -c 'ulimit -c 0; env/bin/python -B -m unittest {pytests} -q && cd apps/lms/frontend && node node_modules/vitest/vitest.mjs run --maxWorkers=1 {uitests} && NODE_OPTIONS=--max-old-space-size=2100 nice -n 15 yarn build'
USER frappe
LABEL org.opencontainers.image.source="https://github.com/institutepsyhology/frappe-lms" org.opencontainers.image.revision="{revision}" ru.mvcentr.baseline="{BASE}" ru.mvcentr.release="course-access-v1"
'''
    (target/'Dockerfile').write_text(recipe, encoding='utf8')
    (target/'manifest.json').write_text(json.dumps({'revision':revision, 'base':BASE,
        'files': {n:hashlib.sha256(raw).hexdigest() for n,raw in files.items()}, 'previous':previous}, indent=2), encoding='utf8')
    print(json.dumps({'revision':revision,'files':len(files)}))


if __name__ == '__main__':
    main()

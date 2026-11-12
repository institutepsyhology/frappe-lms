"""Create a small deterministic Docker context using committed frontend files only."""
import argparse
import hashlib
import io
import json
from pathlib import Path
import re
import subprocess
import tarfile

BASELINE = 'sha256:d4a1f221ed802b0625963909334c067d0ba6f164563193519416537e8d9b2d8d'
FILES = (
    'frontend/src/pages/Courses/CourseDetail.vue',
    'frontend/src/pages/Courses/Courses.vue',
    'frontend/src/tests/courseMemberVisibility.test.ts',
    'frontend/src/tests/coursesDefaultTab.test.ts',
    'frontend/src/tests/coursesFilters.test.ts',
    'frontend/src/tests/courseDetailOutlet.test.ts',
)
HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent


def git_bytes(repo, *args):
    result = subprocess.run(['git', '-C', str(repo), *args], stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, check=True)
    return result.stdout


def create(destination, repo=REPO, revision='HEAD'):
    destination = Path(destination).absolute()
    repo = Path(repo).resolve(strict=True)
    if destination.exists() or destination.is_symlink():
        raise ValueError('context_destination_exists')
    if destination.parent.resolve(strict=True).is_relative_to(repo):
        raise ValueError('context_must_be_outside_checkout')
    commit = git_bytes(repo, 'rev-parse', '--verify', revision + '^{commit}').decode().strip()
    if not re.fullmatch(r'[0-9a-f]{40}', commit):
        raise ValueError('invalid_source_revision')
    sources = {name: git_bytes(repo, 'show', commit + ':' + name) for name in FILES}
    dockerfile = git_bytes(repo, 'show', commit + ':experiments/private-course-access/Dockerfile')
    if dockerfile.count(b'ARG SOURCE_REVISION=unknown') != 1:
        raise ValueError('dockerfile_revision_marker_missing')
    dockerfile = dockerfile.replace(b'ARG SOURCE_REVISION=unknown',
                                    ('ARG SOURCE_REVISION=' + commit).encode())
    if not dockerfile.startswith(('FROM ' + BASELINE + '\n').encode()):
        raise ValueError('dockerfile_baseline_mismatch')
    # This archive contains public Git source only, never backups or credentials.
    destination.mkdir()
    with tarfile.open(destination / 'overlay.tar', 'w', format=tarfile.PAX_FORMAT) as archive:
        for name, content in sources.items():
            info = tarfile.TarInfo(name)
            info.size, info.mode, info.mtime = len(content), 0o644, 0
            info.uid = info.gid = 0
            info.uname = info.gname = ''
            archive.addfile(info, io.BytesIO(content))
    (destination / 'Dockerfile').write_bytes(dockerfile)
    manifest = {'source_revision': commit, 'baseline_image': BASELINE,
                'files': {name: hashlib.sha256(content).hexdigest() for name, content in sources.items()},
                'dockerfile_sha256': hashlib.sha256(dockerfile).hexdigest(),
                'overlay_sha256': hashlib.sha256((destination / 'overlay.tar').read_bytes()).hexdigest()}
    (destination / 'source-manifest.json').write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8')
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('destination')
    parser.add_argument('--revision', default='HEAD')
    args = parser.parse_args()
    print(json.dumps(create(args.destination, revision=args.revision), sort_keys=True))


if __name__ == '__main__':
    main()

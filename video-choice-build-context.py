"""Package only the embedded-video change; optionally build on the LMS host."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess

ROOT = Path(__file__).resolve().parent
BASE_TAG = 'company-lms:russian-2.64.0-20261024'
BASE_ID = 'sha256:35b5b3e30e863b5b4488ee4c60345cebb742cfe4096aa2f582fcd4d62f31229b'
TAG = 'company-lms:video-choice-2.64.0-20261026'
FILES = [
    'frontend/src/utils/index.js',
    'frontend/src/utils/videoChoice.ts',
    'frontend/src/tests/videoChoice.test.ts',
    'video-choice-release.Containerfile',
    'video-choice-deploy.py',
    'russian-deploy.py',
]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory', type=Path)
    parser.add_argument('--build', action='store_true')
    args = parser.parse_args()
    output = args.directory.resolve()
    if output.exists() or output.is_relative_to(ROOT) or ROOT.is_relative_to(output):
        raise RuntimeError('Use a new directory outside the source checkout')
    output.mkdir(parents=True)
    hashes = {}
    for name in FILES:
        source = ROOT/name
        if source.is_symlink() or not source.is_file():
            raise RuntimeError('Unexpected source file')
        target = output/name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        hashes[name] = hashlib.sha256(source.read_bytes().replace(b'\r\n', b'\n')).hexdigest()
    shutil.copyfile(output/'video-choice-release.Containerfile', output/'Dockerfile')
    manifest = {'base_image': BASE_ID, 'source_sha256_lf': hashes}
    (output/'source-manifest.json').write_text(json.dumps(manifest, indent=2)+'\n', encoding='utf8')
    print(json.dumps({'context': str(output), 'files': len(FILES), 'tag': TAG}))
    if args.build:
        actual = subprocess.check_output(['docker', 'image', 'inspect', BASE_TAG, '--format', '{{.Id}}'], text=True).strip()
        if actual != BASE_ID:
            raise RuntimeError('Base image differs from the reviewed release')
        subprocess.run(['docker', 'build', '--network=none', '--pull=false', '--tag', TAG, str(output)], check=True)


if __name__ == '__main__':
    main()

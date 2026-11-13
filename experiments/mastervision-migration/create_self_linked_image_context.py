"""Package only committed self-linked-image Python code on the 48-layer baseline."""
import argparse
import hashlib
import io
import json
from pathlib import Path
import re
import subprocess
import tarfile

REPO = Path(__file__).resolve().parents[2]
BASELINE = 'sha256:03a07ac4a94cb0796c40655018ec69e85b7caf423fd178c45be313f844203f9d'
BASELINE_LAYERS = 48
RELEASE = 'mastervision-self-linked-images-v1'
SOURCE = 'https://github.com/institutepsyhology/frappe-lms'
GENERATOR = 'experiments/mastervision-migration/create_self_linked_image_context.py'
FILES = ('lms/lms/avo_transform.py', 'lms/lms/test_avo_self_linked_images.py')
TESTS = ('test_avo_self_linked_images', 'test_avo_inline_images', 'test_avo_transform',
         'test_avo_html_fragment', 'test_avo_import_unit')


def sha(data): return hashlib.sha256(data).hexdigest()


def sources_digest(files):
    return sha(json.dumps(files, sort_keys=True, separators=(',', ':')).encode())


def dockerfile(revision, files, generator_hash):
    continuation = ' ' + chr(92) + '\n'
    tests = (' &&' + continuation + '    ').join(
        'env/bin/python -B -m unittest lms.lms.' + name + ' -q' for name in TESTS)
    labels = {'org.opencontainers.image.source': SOURCE,
              'org.opencontainers.image.revision': revision,
              'ru.mvcentr.release': RELEASE, 'ru.mvcentr.baseline': BASELINE,
              'ru.mvcentr.sources-sha256': sources_digest(files),
              'ru.mvcentr.generator-sha256': generator_hash}
    label_text = (continuation + '      ').join(f'{key}="{value}"' for key, value in labels.items())
    return (f'FROM {BASELINE}\nUSER frappe\nWORKDIR /home/frappe/frappe-bench\n'
            'ADD --chown=frappe:0 overlay.tar apps/lms/\n'
            f'RUN {tests}\nLABEL {label_text}\n').encode()


def git_bytes(repo, *args):
    return subprocess.run(['git', '-C', str(repo), *args], check=True,
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE).stdout


def create(destination, repo=REPO, revision='HEAD'):
    repo, destination = Path(repo).resolve(strict=True), Path(destination).absolute()
    if destination.exists() or destination.is_symlink(): raise ValueError('context_destination_exists')
    if destination.parent.resolve(strict=True).is_relative_to(repo):
        raise ValueError('context_must_be_outside_checkout')
    commit = git_bytes(repo, 'rev-parse', '--verify', revision + '^{commit}').decode().strip()
    if not re.fullmatch(r'[0-9a-f]{40}', commit): raise ValueError('invalid_source_revision')
    generator = git_bytes(repo, 'show', commit + ':' + GENERATOR)
    normalized_generator = generator.replace(b'\r\n', b'\n')
    if normalized_generator != Path(__file__).read_bytes().replace(b'\r\n', b'\n'):
        raise ValueError('context_generator_not_committed_revision')
    sources = {name: git_bytes(repo, 'show', commit + ':' + name) for name in FILES}
    if any(not data or len(data) > 2_000_000 for data in sources.values()):
        raise ValueError('invalid_source_file')
    files = {name: sha(data) for name, data in sources.items()}
    recipe = dockerfile(commit, files, sha(normalized_generator))
    destination.mkdir()
    with tarfile.open(destination / 'overlay.tar', 'w', format=tarfile.PAX_FORMAT) as archive:
        for name, data in sources.items():
            info = tarfile.TarInfo(name)
            info.size, info.mode, info.mtime = len(data), 0o644, 0
            info.uid = info.gid = 0; info.uname = info.gname = ''
            archive.addfile(info, io.BytesIO(data))
    (destination / 'Dockerfile').write_bytes(recipe)
    manifest = {'release': RELEASE, 'source': SOURCE, 'source_revision': commit,
                'baseline_image': BASELINE, 'baseline_layers': BASELINE_LAYERS,
                'files': files, 'generator_sha256': sha(normalized_generator),
                'dockerfile_sha256': sha(recipe),
                'overlay_sha256': sha((destination / 'overlay.tar').read_bytes())}
    (destination / 'source-manifest.json').write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8')
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('destination'); parser.add_argument('--revision', default='HEAD')
    args = parser.parse_args()
    print(json.dumps(create(args.destination, revision=args.revision), sort_keys=True))


if __name__ == '__main__': main()

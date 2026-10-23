"""Create a minimal source-only context for the pinned Russian LMS image.

Usage: python russian-build-context.py NEW_DIRECTORY [--build]
The output must not already exist. Run --build on the Docker host with the
verified original company-lms image available locally; no dependency downloads.
"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess

BASE_COMMIT='7c46bb8f4976222b3f6aa84368551c424edaa194'
BASE_IMAGE='company-lms:lms-2.64.0-frappe-16.53.0'
BASE_IMAGE_ID='sha256:30a77dba1c33dcd3e221c17a54806dc5ac64f718a11093e3186dc1cfc23653dc'
TAG='company-lms:russian-2.64.0-20261024'
ROOT=Path(__file__).resolve().parent


def build_context(destination):
    destination=destination.resolve()
    if destination.exists() or destination == ROOT or ROOT.is_relative_to(destination):
        raise RuntimeError('Use a new output directory outside the repository')
    paths=set(subprocess.check_output(['git','diff',BASE_COMMIT,'--name-only','--diff-filter=ACM'],cwd=ROOT,text=True).splitlines())
    paths.update(subprocess.check_output(['git','ls-files','--others','--exclude-standard'],cwd=ROOT,text=True).splitlines())
    files={}
    for name in sorted(paths):
        path=(ROOT/name).resolve()
        if not path.is_relative_to(ROOT) or path.is_symlink() or not path.is_file():
            raise RuntimeError('Unexpected source path')
        if any(part in {'.git','node_modules','private','secrets','__pycache__'} for part in Path(name).parts) or name.endswith(('.env','.pem','.key','.sqlite','.tar','.zip')):
            raise RuntimeError('Non-source file excluded from release')
        if path.stat().st_size>3_000_000:
            raise RuntimeError('Unexpected source size')
        files[name]=hashlib.sha256(path.read_bytes()).hexdigest()
    if not files:
        raise RuntimeError('No source changes')
    destination.mkdir(parents=True)
    for name in files:
        target=destination/'source'/name
        target.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(ROOT/name,target)
    shutil.copyfile(ROOT/'russian-release.Containerfile',destination/'Dockerfile')
    manifest={'baseline_commit':BASE_COMMIT,'baseline_image':BASE_IMAGE_ID,'release':'2.64.0-ru.20261024','files':files}
    (destination/'russian-source-manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    return destination,manifest


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory',type=Path)
    parser.add_argument('--build',action='store_true')
    args=parser.parse_args()
    destination,manifest=build_context(args.directory)
    print(json.dumps({'context':str(destination),'source_files':len(manifest['files']),'tag':TAG}))
    if args.build:
        actual=subprocess.check_output(['docker','image','inspect',BASE_IMAGE,'--format','{{.Id}}'],text=True).strip()
        if actual!=BASE_IMAGE_ID:
            raise RuntimeError('Base image differs from the verified production baseline')
        subprocess.run(['docker','build','--network=none','--pull=false','--tag',TAG,str(destination)],check=True)

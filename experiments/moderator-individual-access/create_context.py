"""Package only reviewed source files; do not include exports or secrets."""
import argparse
import hashlib
import io
import json
from pathlib import Path
import shutil
import tarfile

ROOT=Path(__file__).resolve().parents[2]
FILES=[
 'frontend/src/components/Courses/IndividualAccessSettings.vue',
 'frontend/src/components/Courses/LessonAccessSettings.vue',
 'frontend/src/tests/individualAccessSettings.test.ts',
 'frontend/src/tests/lessonAccessSettings.test.ts',
 'lms/lms/access_actions.py',
]
BASE='sha256:c5f2923ddcabae5ed22bd46fcc3a4b2f60078f7be745d94261c52b9115026247'


def main():
    parser=argparse.ArgumentParser();parser.add_argument('directory',type=Path);args=parser.parse_args()
    out=args.directory.resolve()
    if out.exists() or out==ROOT or ROOT in out.parents:
        raise ValueError('use a new directory outside the source checkout')
    out.mkdir(parents=True)
    hashes={}
    with tarfile.open(out/'overlay.tar','w') as archive:
        for name in FILES:
            path=ROOT/name
            if path.is_symlink() or not path.is_file():raise ValueError('unexpected source path')
            data=path.read_bytes().replace(b'\r\n',b'\n')
            hashes[name]=hashlib.sha256(data).hexdigest()
            item=tarfile.TarInfo(name);item.size=len(data);item.mode=0o644;item.mtime=0
            archive.addfile(item,io.BytesIO(data))
    shutil.copyfile(ROOT/'experiments/moderator-individual-access/Dockerfile',out/'Dockerfile')
    (out/'source-manifest.json').write_text(json.dumps({'base_image':BASE,'source_sha256_lf':hashes},indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'files':len(FILES),'base_image':BASE}))


if __name__=='__main__':main()

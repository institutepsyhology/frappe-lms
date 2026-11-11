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
    'frontend/src/components/Sidebar/UserDropdown.vue',
    'frontend/src/utils/settingsAccess.ts',
    'frontend/src/tests/settingsAccess.test.ts',
    'frontend/src/components/Settings/CredentialProfiles.vue',
    'frontend/src/components/Settings/AvoContactCard.vue',
]
BASE='sha256:5f8873552da789e39140110d5876ab64a6925773df47053027c4f9b89c49f991'


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
    shutil.copyfile(ROOT/'experiments/avo-credential-profiles-interface/Dockerfile',out/'Dockerfile')
    (out/'source-manifest.json').write_text(json.dumps({'base_image':BASE,'source_sha256_lf':hashes},indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'files':len(FILES),'base_image':BASE}))


if __name__=='__main__':main()

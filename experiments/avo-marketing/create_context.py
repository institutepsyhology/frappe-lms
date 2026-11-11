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
    'frontend/src/components/Settings/AvoContactCard.vue',
    'frontend/src/components/Settings/Members.vue',
    'frontend/src/components/Sidebar/UserDropdown.vue',
    'frontend/src/pages/ContactDirectory.vue',
    'frontend/src/pages/Forms/MemberForm.vue',
    'frontend/src/routes.js',
    'frontend/src/types/api.ts',
    'frontend/src/tests/avoContactCard.test.ts',
    'lms/hooks.py',
    'lms/lms/api.py',
    'lms/lms/utils.py',
    'lms/lms/avo_contact_card.py',
    'lms/lms/avo_contact_fields.py',
    'lms/lms/avo_contact_identity.py',
    'lms/lms/avo_marketing.py',
    'lms/lms/test_avo_marketing_unit.py',
    'lms/lms/avo_user_import.py',
    'lms/lms/support_credentials.py',
    'lms/lms/test_avo_user_import_unit.py',
    'lms/locale/ru.po',
]
BASE='sha256:fb757e3f6b27d6046ecc0f9406bdd3569c3ca56ae1b8207b1bb651f6de7df845'


def main():
    parser=argparse.ArgumentParser();parser.add_argument('directory',type=Path);parser.add_argument('--frontend',action='store_true');args=parser.parse_args()
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
    base='sha256:3831530e82848dc458dd8d88e8169821cbbfa87dde75089049084c8c9959f431' if args.frontend else BASE
    dockerfile='Dockerfile.frontend' if args.frontend else 'Dockerfile'
    shutil.copyfile(ROOT/'experiments/avo-marketing'/dockerfile,out/'Dockerfile')
    (out/'source-manifest.json').write_text(json.dumps({'base_image':base,'source_sha256_lf':hashes},indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'files':len(FILES),'base_image':base}))


if __name__=='__main__':main()

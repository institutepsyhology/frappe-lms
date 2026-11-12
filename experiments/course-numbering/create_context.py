"""Package only committed source and tests for the AVO editor release."""
import hashlib, io, json, subprocess, sys, tarfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
FILES=['lms/hooks.py',
 'lms/lms/course_numbering.py',
 'lms/lms/test_course_numbering_unit.py',
 'lms/lms/avo_course_routes.py',
 'lms/lms/test_avo_course_routes_unit.py',
 'lms/lms/avo_import.py',
 'lms/lms/test_avo_import_unit.py']
def main():
 out=Path(sys.argv[1]).resolve();out.mkdir(parents=True,exist_ok=False)
 commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip();hashes={}
 with tarfile.open(out/'overlay.tar','w') as tar:
  for name in FILES:
   data=subprocess.check_output(['git','show',f'{commit}:{name}'],cwd=ROOT).replace(b'\r\n',b'\n');hashes[name]=hashlib.sha256(data).hexdigest()
   info=tarfile.TarInfo(name);info.size=len(data);info.mode=0o644;info.mtime=0;tar.addfile(info,io.BytesIO(data))
 (out/'Dockerfile').write_bytes((ROOT/'experiments/course-numbering/Dockerfile').read_bytes().replace(b'\r\n',b'\n'))
 (out/'manifest.json').write_text(json.dumps({'commit':commit,'sha256':hashes},indent=2),encoding='utf-8')
 print(json.dumps({'commit':commit,'files':len(FILES)}))
if __name__=='__main__':main()

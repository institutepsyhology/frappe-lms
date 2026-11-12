"""Package only committed source and tests for the AVO editor release."""
import hashlib, io, json, subprocess, sys, tarfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
FILES=['lms/hooks.py',
 'lms/lms/avo_course_routes.py',
 'lms/lms/test_avo_course_routes_unit.py',
 'frontend/src/router.js',
 'frontend/src/routes.js',
 'frontend/src/utils/avoCourseRoutes.ts',
 'frontend/src/pages/Courses/AvoLessonEditor.vue',
 'frontend/src/pages/Courses/AvoCourseStart.vue',
 'frontend/src/components/Sidebar/UserDropdown.vue',
 'frontend/src/components/CourseCardOverlay.vue',
 'frontend/src/tests/avoCourseRoutes.test.ts',
 'experiments/avo-exact-urls/apply_live_delta.py']
def main():
 out=Path(sys.argv[1]).resolve();out.mkdir(parents=True,exist_ok=False)
 commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip();hashes={}
 with tarfile.open(out/'overlay.tar','w') as tar:
  for name in FILES:
   data=subprocess.check_output(['git','show',f'{commit}:{name}'],cwd=ROOT).replace(b'\r\n',b'\n');hashes[name]=hashlib.sha256(data).hexdigest()
   info=tarfile.TarInfo(name);info.size=len(data);info.mode=0o644;info.mtime=0;tar.addfile(info,io.BytesIO(data))
 (out/'Dockerfile').write_bytes((ROOT/'experiments/avo-exact-urls/Dockerfile').read_bytes().replace(b'\r\n',b'\n'))
 (out/'manifest.json').write_text(json.dumps({'commit':commit,'sha256':hashes},indent=2),encoding='utf-8')
 print(json.dumps({'commit':commit,'files':len(FILES)}))
if __name__=='__main__':main()

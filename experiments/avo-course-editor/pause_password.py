"""Pause the password worker at a journal checkpoint during activation."""
import importlib.util,json,subprocess,sys,time
from pathlib import Path
HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('pause_common',HERE.parent/'avo-contact-id/pause_and_switch.py')
common=importlib.util.module_from_spec(spec);spec.loader.exec_module(common)

def main():
 if len(sys.argv)==3 and sys.argv[1]=='--watchdog':return common.watchdog(Path(sys.argv[2]))
 if len(sys.argv)<4 or sys.argv[2]!='--':raise SystemExit('usage: pause_password.py PID -- command ...')
 root=HERE.parents[2]/'exports/contacts-api-all-fields';marker=root/'course-editor-switch-pause.json'
 pid=int(sys.argv[1]);h=common.handle(pid);suspended=False;owned=False
 try:
  with marker.open('x',encoding='utf-8') as out:json.dump({'processes':[{'pid':pid,'creation':common.creation(h)}]},out)
  owned=True
  subprocess.Popen([sys.executable,str(Path(__file__).resolve()),'--watchdog',str(marker)],creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
  with (root/'mvcentr-support-password-events.jsonl').open('r',encoding='utf-8') as stream:
   stream.seek(0,2);deadline=time.monotonic()+90
   while time.monotonic()<deadline:
    line=stream.readline()
    if not line:time.sleep(.01);continue
    if json.loads(line).get('status')!='stored':continue
    if common.N.NtSuspendProcess(h)!=0:raise OSError('pause_failed')
    suspended=True;print('password_worker_paused',flush=True);break
   else:raise TimeoutError('no_safe_checkpoint')
  return subprocess.run(sys.argv[3:],timeout=600).returncode
 finally:
  if suspended:common.N.NtResumeProcess(h)
  common.K.CloseHandle(h)
  if owned:marker.unlink(missing_ok=True)
  print('password_worker_resumed',flush=True)
if __name__=='__main__':raise SystemExit(main() or 0)

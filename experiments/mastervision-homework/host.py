"""Host half of rollout.py. Trial only builds images. Published revisions use the existing guarded activation."""
import base64
import contextlib
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile

BASE = "sha256:01fbbaeecbd04e4db7af2f6eaf30bd84ed38d5b3270e97c3e47123b59e998573"
TAG = "company-lms:course-access-7924cbb5"
RELEASE = "mv-homework-v1"
BENCH = "/home/frappe/frappe-bench"
APP = BENCH + "/apps/lms"
LIVE = "company-lms-backend-1"
UI = "frontend/src/components/Assignment.vue"
ROOT = Path("/opt/company-lms")
SHA_READER = """import sys,json,hashlib;from pathlib import Path
p=Path('/home/frappe/frappe-bench/apps/lms')
print(json.dumps({f:hashlib.sha256((p/f).read_bytes().replace(b'\\r\\n',b'\\n')).hexdigest() if (p/f).is_file() else None for f in sys.argv[1:]}))"""


def run(*args):
    return subprocess.check_output(args, text=True).strip()


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def available():
    return shutil.disk_usage(ROOT).free


def verify_stage(image, files):
    stage = files["experiments/mastervision-homework/stage.py"].decode()
    tests = {name:base64.b64encode(raw).decode() for name,raw in files.items() if Path(name).name.startswith("test_")}
    args = ["docker","run","--rm","--pull=never","-i","--network=company-lms-access-stage-20261027",
            "--volumes-from=company-lms-access-stage-app-20261027","-u","frappe","-w",BENCH+"/sites",
            "--entrypoint="+BENCH+"/env/bin/python",image,"-B","-W","ignore::SyntaxWarning","-c",stage,SCHEMA]
    subprocess.run(args, input=json.dumps(tests).encode(), timeout=360, check=True)


def build_delta(folder, tag, base, files, labels, *, frontend=False):
    """Share the active overlay snapshot. BuildKit would unpack the 52-layer base again."""
    folder.mkdir()
    config = json.loads(run("docker", "image", "inspect", base))[0]["Config"]
    container = run("docker", "create", "--network=none", "--entrypoint=sleep", base, "3600")
    try:
        run("docker", "start", container)
        data = io.BytesIO()
        with tarfile.open(fileobj=data, mode="w", format=tarfile.USTAR_FORMAT) as tar:
            for name in sorted(files):
                item = tarfile.TarInfo(name)
                item.size, item.mode, item.uid, item.gid = len(files[name]), 0o644, 1000, 0
                tar.addfile(item, io.BytesIO(files[name]))
        subprocess.run(["docker","exec","-i","-u","root",container,"tar","-xf","-","-C",APP],
                       input=data.getvalue(),check=True)
        if frontend:
            log = folder/"build.log"
            with log.open("wb") as stream:
                job = subprocess.run(["docker","exec","-u","frappe","-w",APP+"/frontend",container,"sh","-ec",
                    "node node_modules/vitest/vitest.mjs run --maxWorkers=1 src/tests/assignmentRoute.test.ts "
                    "src/tests/assignmentStudentView.test.ts && NODE_OPTIONS=--max-old-space-size=2100 nice -n 15 yarn build"],
                    stdout=stream,stderr=subprocess.STDOUT,timeout=1800)
            if job.returncode:
                print(log.read_text(errors="replace")[-3000:],flush=True)
                raise RuntimeError("homework_frontend_build_failed")
            check="""from pathlib import Path
p=Path('apps/lms/lms/public/frontend')
assert (p/'index.html').read_bytes()==Path('apps/lms/lms/www/_lms.html').read_bytes()
assert any('avo_allow_attachments' in f.read_text() for f in p.glob('assets/*.js'))"""
            run("docker","exec",container,"python","-B","-c",check)
        changes = ["ENTRYPOINT "+json.dumps(config["Entrypoint"]),"CMD "+json.dumps(config["Cmd"])]
        changes.extend("LABEL "+k+"="+json.dumps(v) for k,v in labels.items())
        image = run("docker","commit",*[v for cmd in changes for v in ("--change",cmd)],container,tag)
        actual = json.loads(run("docker","image","inspect",image))[0]["Config"]
        if any(config.get(k)!=actual.get(k) for k in ("User","WorkingDir","Entrypoint","Cmd","Env","Volumes","ExposedPorts","Healthcheck")):
            raise RuntimeError("container_configuration_changed")
        return image
    finally:
        subprocess.run(["docker","rm","-f","-v",container],check=True,stdout=subprocess.DEVNULL)


def build_candidate(tmp, request, files):
    if run("docker", "inspect", "--format", "{{.Image}}", LIVE) != BASE or run("docker", "image", "inspect", "--format", "{{.Id}}", TAG) != BASE:
        raise RuntimeError("baseline_changed")
    if available() < 800*1024**2:
        raise RuntimeError("insufficient_space_for_frontend")
    prev = request["previous"]
    live = json.loads(run("docker", "exec", LIVE, "python", "-B", "-c", SHA_READER, *prev))
    drift = [f for f in prev if live[f] != prev[f] and live[f] != digest(files[f])]
    if drift:
        raise RuntimeError("live_source_changed: "+str(drift))
    ui_tag = "company-lms:mv-homework-ui-"+digest(files[UI])[:16]
    print("Building and testing learner interface", flush=True)
    cached = subprocess.run(["docker","image","inspect",ui_tag], capture_output=True)
    ui_source = digest(files[UI])
    if cached.returncode == 0:
        cached_image = json.loads(cached.stdout)[0]
        labels = cached_image["Config"].get("Labels") or {}
        if labels.get("ru.mvcentr.ui-source") != ui_source or labels.get("ru.mvcentr.ui-baseline") != BASE:
            raise RuntimeError("ui_cache_identity_mismatch")
        ui = cached_image["Id"]
    else:
        ui = build_delta(tmp/"ui", ui_tag, BASE, {UI:files[UI]}, {"ru.mvcentr.ui-source":ui_source,
                         "ru.mvcentr.ui-baseline":BASE}, frontend=True)
    app = {name:data for name,data in files.items() if name in prev and name != UI}
    sha = digest(b"".join(name.encode()+b"\0"+app[name]+b"\0" for name in sorted(app)) + files[UI])
    trial = request["action"] == "trial"
    revision = "trial-"+sha[:20] if trial else request["revision"]
    tag = "company-lms:mv-homework-"+revision[:24]
    image = build_delta(tmp/"backend", tag, ui, app, {
        "org.opencontainers.image.source":"https://github.com/institutepsyhology/frappe-lms",
        "org.opencontainers.image.revision":revision,"ru.mvcentr.baseline":BASE,"ru.mvcentr.release":RELEASE})
    actual = json.loads(run("docker", "run", "--rm", "--network=none", "--entrypoint=python", image,
                            "-B", "-c", SHA_READER, *prev))
    if any(actual[name] != digest(files[name]) for name in prev):
        raise RuntimeError("candidate_source_mismatch")
    print(json.dumps({"verified_image":image,"revision":revision,"free_bytes":available()}), flush=True)
    return image


SCHEMA = """import frappe,sys,json
from frappe.core.doctype.scheduled_job_type.scheduled_job_type import insert_single_event
site=sys.argv[1];frappe.init(site=site);frappe.connect();frappe.set_user('Administrator')
try:
 stage=site=='access-stage2.local' and frappe.conf.allow_tests and frappe.conf.db_host=='db'
 assert stage or site in ('my-lk.mv-centr.ru','my-lk.mastervision.su','my-lk.iomp.ru')
 assert stage or frappe.conf.get('encryption_key'), 'existing_key_required'
 method='lms.lms.avo_homework_approval.approve_due'
 existing_job=bool(frappe.db.exists('Scheduled Job Type',{'method':method}))
 for doctype in ('lms_assignment','lms_assignment_submission'):
  frappe.reload_doc('lms','doctype',doctype,force=True)
 frappe.clear_cache()
 for dt,fields in {'LMS Assignment':('avo_optional','avo_allow_attachments','avo_auto_approve','avo_auto_approve_hours'),'LMS Assignment Submission':('avo_answer_submitted_at',)}.items():
  assert all(frappe.get_meta(dt).has_field(n) and frappe.db.has_column(dt,n) for n in fields)
 assert all(str(frappe.get_meta('LMS Assignment').get_field(n).default)=='0'
            for n in ('avo_optional','avo_allow_attachments','avo_auto_approve','avo_auto_approve_hours'))
 if sys.argv[2]=='enable':
  assert method in frappe.get_hooks('scheduler_events')['all']
  insert_single_event('All',method)
  assert frappe.db.exists('Scheduled Job Type',{'method':method,'frequency':'All'})
 frappe.db.commit();frappe.clear_cache()
 print(json.dumps({'site':site,'homework_schema':True,'scheduler_registered':sys.argv[2]=='enable',
                   'existing_job':existing_job}))
finally: frappe.destroy()"""


def activate(tmp, request, image, files):
    for name, data in files.items():
        if name.startswith("experiments/"):
            p = tmp/name
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(data)
    path = tmp/"experiments/private-course-access/release.py"
    spec = importlib.util.spec_from_file_location("homework_shared_release", path)
    shared = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(shared)
    shared.BASELINE, shared.RELEASE = BASE, RELEASE

    def schema(module):
        # User-facing catalogs are in the shared sites/assets volume.
        module.run(["docker","exec","-u","frappe","-w",BENCH,LIVE,"bench","compile-po-to-mo",
                    "--app","lms","--locale","ru","--force"],timeout=150)
        return [json.loads(module.run(["docker","exec","-u","frappe","-w",BENCH+"/sites",LIVE,
            BENCH+"/env/bin/python","-B","-c",SCHEMA,site,"enable"],timeout=240)) for site in shared.SITES]

    shared.clear_site_caches = schema
    with shared.release_lock():
        if available() < 1024**3:
            raise RuntimeError("insufficient_space_for_fresh_backups")
        verify_keys = "import frappe,sys\nfor s in sys.argv[1:]:\n frappe.init(site=s);assert frappe.conf.get('encryption_key');frappe.destroy()"
        run("docker","exec","-u","frappe","-w",BENCH+"/sites",LIVE,BENCH+"/env/bin/python","-B","-c",verify_keys,*shared.SITES)
        result = io.StringIO()
        with contextlib.redirect_stdout(result):
            shared.prepare(keep_database_staging=False)
        manifest = json.loads(result.getvalue())["backup_manifest"]
        print("Three current database backups verified", flush=True)
        networks = json.loads(run("docker","inspect","--format","{{json .NetworkSettings.Networks}}",LIVE))
        if len(networks) != 1:
            raise RuntimeError("unexpected_application_network")
        old_jobs = {}
        for site in shared.SITES:
            check = run("docker","run","--rm","--network",next(iter(networks)),"--volumes-from",LIVE,
                "--entrypoint",BENCH+"/env/bin/python","-w",BENCH+"/sites",image,"-B","-c",SCHEMA,site,"prepare")
            old_jobs[site] = json.loads(check)["existing_job"]
        rc = shared.activate(image, manifest, request["revision"])
        if rc and run("docker","inspect","--format","{{.Image}}",LIVE) == BASE:
            undo = """import sys,frappe
frappe.init(site=sys.argv[1]);frappe.connect();frappe.set_user('Administrator')
try:
 method='lms.lms.avo_homework_approval.approve_due'
 job=frappe.db.exists('Scheduled Job Type',{'method':method})
 if job: frappe.delete_doc('Scheduled Job Type',job)
 frappe.db.commit();frappe.clear_cache()
finally: frappe.destroy()"""
            for site in shared.SITES:
                if not old_jobs[site]:
                    run("docker","exec","-u","frappe","-w",BENCH+"/sites",LIVE,BENCH+"/env/bin/python","-B","-c",undo,site)
        return rc


if __name__ == "__main__":
    data = json.load(sys.stdin)
    if run("hostname") != "spb-3-vm-t6fa" or os.geteuid() or data["action"] not in ("trial","publish") or not re.fullmatch(r"[a-f0-9]{40}", data["revision"]):
        raise ValueError("wrong_target_or_action")
    os.umask(0o077)
    files = {k:base64.b64decode(v,validate=True) for k,v in data["files"].items()}
    if any(Path(k).is_absolute() or ".." in Path(k).parts for k in files):
        raise ValueError("source_path_invalid")
    with tempfile.TemporaryDirectory(prefix="mv-homework-build-",dir=ROOT) as folder:
        tmp = Path(folder)
        candidate = build_candidate(tmp, data, files)
        verify_stage(candidate, files)
        if data["action"] == "publish":
            sys.exit(activate(tmp, data, candidate, files))

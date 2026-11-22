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
SERVICES = ("backend", "frontend", "websocket", "queue-short", "queue-long", "scheduler")
HOOK = "lms/hooks.py"
HOOK_PATH = APP + "/" + HOOK
OLD_BIND = str(ROOT / "overlays/contact-binding-555e664bae82dae7761ace738f807195dd4ddd6b/lms/hooks.py")
JOB_LINE = b'\t\t"lms.lms.avo_homework_approval.approve_due",\n'
CONTACT = "lms/lms/avo_contact_binding.py"
SHA_READER = """import sys,json,hashlib;from pathlib import Path
p=Path('/home/frappe/frappe-bench/apps/lms')
print(json.dumps({f:hashlib.sha256((p/f).read_bytes().replace(b'\\r\\n',b'\\n')).hexdigest() if (p/f).is_file() else None for f in sys.argv[1:]}))"""


def run(*args):
    return subprocess.check_output(args, text=True).strip()


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def available():
    return shutil.disk_usage(ROOT).free


def compose_plan(config):
    """Remove only the redundant, version-pinned hooks mount from all six services."""
    line = (OLD_BIND + ":" + HOOK_PATH + ":ro").encode()
    lines = config.splitlines(keepends=True)
    updated = b"".join(row for row in lines if row.strip() != b"- " + line)
    if sum(row.strip() == b"- " + line for row in lines) != len(SERVICES):
        raise RuntimeError("unexpected_hooks_mount_count")

    def render(data):
        proc = subprocess.run(["docker", "compose", "--project-directory", str(ROOT / "runtime"),
                               "--profile", "jobs", "-f", "-", "config", "--format", "json"],
                              input=data, capture_output=True, timeout=45)
        if proc.returncode:
            raise RuntimeError("compose_validation_failed")
        return json.loads(proc.stdout)

    expected = render(config)
    for service in SERVICES:
        mounts = expected["services"][service]["volumes"]
        matches = [m for m in mounts if m["target"] == HOOK_PATH]
        if len(matches) != 1 or matches[0]["type"] != "bind" or matches[0]["source"] != OLD_BIND or not matches[0].get("read_only"):
            raise RuntimeError("unexpected_hooks_mount:" + service)
        mounts.remove(matches[0])
    if render(updated) != expected:
        raise RuntimeError("other_compose_settings_changed")
    return updated


class RuntimeLayout:
    def __init__(self, image, files, app_paths):
        self.config = ROOT / "runtime/compose.yaml"
        if self.config.is_symlink() or self.config.stat().st_uid:
            raise RuntimeError("unexpected_compose_owner")
        self.before = self.config.read_bytes()
        self.after = compose_plan(self.before)
        self.written = False
        old_hook = Path(OLD_BIND).read_bytes()
        if files[HOOK].count(JOB_LINE) != 1 or files[HOOK].replace(JOB_LINE, b"") != old_hook:
            raise RuntimeError("candidate_does_not_preserve_contact_hooks")
        base_hash = json.loads(run("docker", "run", "--rm", "--read-only", "--network=none",
                                   "--entrypoint=python", BASE, "-B", "-c", SHA_READER, HOOK))[HOOK]
        if base_hash != digest(old_hook):
            raise RuntimeError("original_image_needs_hooks_mount")
        self.expected = {name: digest(files[name]) for name in app_paths}
        mounted = None
        for service in SERVICES:
            container = "company-lms-" + service + "-1"
            rows = json.loads(run("docker", "inspect", "--format", "{{json .Mounts}}", container))
            code_mounts = {}
            for m in rows:
                dest = Path(m["Destination"])
                if dest == Path(APP) or dest in Path(APP).parents:
                    raise RuntimeError("unexpected_application_parent_mount:" + service)
                if not dest.is_relative_to(APP):
                    continue
                if m["Type"] != "bind" or m["RW"] or not Path(m["Source"]).is_file():
                    raise RuntimeError("unexpected_application_mount:" + service)
                code_mounts[str(dest.relative_to(APP))] = m["Source"]
            if code_mounts.get(HOOK) != OLD_BIND or CONTACT not in code_mounts:
                raise RuntimeError("contact_overlay_changed:" + service)
            if mounted is not None and mounted != code_mounts:
                raise RuntimeError("service_code_mounts_differ:" + service)
            mounted = code_mounts
        binds = []
        for name, source in mounted.items():
            if name != HOOK:
                binds.extend(["--mount", "type=bind,source="+source+",target="+APP+"/"+name+",readonly"])
                file_hash = digest(Path(source).read_bytes().replace(b"\r\n", b"\n"))
                if name in self.expected and self.expected[name] != file_hash:
                    raise RuntimeError("another_mount_masks_release_file:" + name)
                self.expected[name] = file_hash
        # Reproduce effective application mounts without any database, network or writable production volumes.
        check = ["docker", "run", "--rm", "--network=none", "--read-only", *binds,
                 "--entrypoint="+BENCH+"/env/bin/python", image, "-B", "-c"]
        if json.loads(run(*check, SHA_READER, *self.expected)) != self.expected:
            raise RuntimeError("effective_candidate_files_differ")
        contact_check = """import lms.hooks as hooks
from lms.lms.avo_contact_binding import AvoContactIdentityMixin
from lms.lms.avo_homework_approval import approve_due
assert 'lms.lms.avo_contact_binding.AvoContactIdentityMixin' in hooks.extend_doctype_class['Contact']
assert 'lms.lms.avo_homework_approval.approve_due' in hooks.scheduler_events['all']"""
        run(*check, contact_check)
        print("Six service layouts, effective candidate files and contact binding verified", flush=True)

    def replace(self, expected, data):
        if self.config.read_bytes() != expected:
            raise RuntimeError("runtime_compose_changed")
        meta = self.config.stat()
        with tempfile.NamedTemporaryFile(dir=self.config.parent, delete=False) as f:
            p = Path(f.name)
            try:
                os.fchown(f.fileno(), meta.st_uid, meta.st_gid)
                os.fchmod(f.fileno(), meta.st_mode & 0o777)
                f.write(data)
                f.flush()
                os.fsync(f.fileno())
                os.replace(p, self.config)
            finally:
                p.unlink(missing_ok=True)

    def apply(self, backup_dir):
        with (backup_dir / "compose.yaml.before").open("xb") as f:
            f.write(self.before)
            f.flush()
            os.fsync(f.fileno())
        self.replace(self.before, self.after)
        self.written = True

    def restore(self):
        if self.written:
            self.replace(self.after, self.before)
            self.written = False

    def verify_active(self):
        for service in SERVICES:
            container = "company-lms-" + service + "-1"
            actual = json.loads(run("docker", "exec", container, "python", "-B", "-c", SHA_READER, *self.expected))
            if actual != self.expected:
                raise RuntimeError("active_source_mismatch:" + service)


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
site=sys.argv[1];step='connect'
try:
 frappe.init(site=site);frappe.connect();frappe.set_user('Administrator')
 step='check_site'
 stage=site=='access-stage2.local' and frappe.conf.allow_tests and frappe.conf.db_host=='db'
 assert stage or site in ('my-lk.mv-centr.ru','my-lk.mastervision.su','my-lk.iomp.ru')
 assert stage or frappe.conf.get('encryption_key'), 'existing_key_required'
 method='lms.lms.avo_homework_approval.approve_due'
 existing_job=bool(frappe.db.exists('Scheduled Job Type',{'method':method}))
 if sys.argv[2]=='prepare':
  for doctype in ('lms_assignment','lms_assignment_submission'):
   step='reload_'+doctype
   frappe.reload_doc('lms','doctype',doctype,force=True)
 step='verify_schema'
 frappe.clear_cache()
 for dt,fields in {'LMS Assignment':('avo_optional','avo_allow_attachments','avo_auto_approve','avo_auto_approve_hours'),'LMS Assignment Submission':('avo_answer_submitted_at',)}.items():
  assert all(frappe.get_meta(dt).has_field(n) and frappe.db.has_column(dt,n) for n in fields)
 assert all(str(frappe.get_meta('LMS Assignment').get_field(n).default)=='0'
            for n in ('avo_optional','avo_allow_attachments','avo_auto_approve','avo_auto_approve_hours'))
 if sys.argv[2]=='enable':
  step='verify_contact_binding'
  from lms.lms.avo_contact_binding import binding_status
  assert binding_status()['active']
  step='verify_scheduler_hook'
  assert method in frappe.get_hooks('scheduler_events')['all']
  step='register_scheduler_job'
  insert_single_event('All',method)
  assert frappe.db.exists('Scheduled Job Type',{'method':method,'frequency':'All'})
 step='commit_schema'
 frappe.db.commit();frappe.clear_cache()
 print(json.dumps({'site':site,'homework_schema':True,'scheduler_registered':sys.argv[2]=='enable',
                   'existing_job':existing_job}))
except Exception as exc:
 print('HOMEWORK_SETUP='+step+':'+type(exc).__name__,file=sys.stderr)
 sys.exit(1)
finally: frappe.destroy()"""


def checked_setup(site, phase, cmd):
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=240)
    except subprocess.TimeoutExpired:
        raise RuntimeError("homework_setup:"+site+":"+phase+":timeout") from None
    if proc.returncode:
        marker = re.search(r"(?m)^HOMEWORK_SETUP=([a-z_]+:[A-Za-z][A-Za-z0-9_]*)$", proc.stderr)
        detail = marker.group(1) if marker else "exit_"+str(proc.returncode)
        raise RuntimeError("homework_setup:"+site+":"+phase+":"+detail)
    return proc.stdout.strip()


def backup_for_activation(shared):
    manifests = sorted((ROOT / "backups").glob("contact-card-*/manifest.json"))
    if manifests:
        try:
            shared.validate_backup(manifests[-1])
        except RuntimeError as exc:
            if str(exc) not in ("backup_not_fresh", "backup_release_mismatch"):
                raise
        else:
            print("Three existing database backups verified again (maximum age two hours)", flush=True)
            return str(manifests[-1])
    if available() < 1024**3:
        raise RuntimeError("insufficient_space_for_fresh_backups")
    output = io.StringIO()
    with contextlib.redirect_stdout(output):
        shared.prepare(keep_database_staging=False)
    print("Three fresh database backups verified", flush=True)
    return json.loads(output.getvalue())["backup_manifest"]


def activate(tmp, request, image, files, layout):
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
        layout.verify_active()
        checked_setup("shared","compile_translations",["docker","exec","-u","frappe","-w",BENCH,LIVE,
                      "bench","compile-po-to-mo","--app","lms","--locale","ru","--force"])
        return [json.loads(checked_setup(site,"enable",["docker","exec","-u","frappe","-w",BENCH+"/sites",LIVE,
            BENCH+"/env/bin/python","-B","-c",SCHEMA,site,"enable"])) for site in shared.SITES]

    shared.clear_site_caches = schema
    with shared.release_lock():
        verify_keys = "import frappe,sys\nfor s in sys.argv[1:]:\n frappe.init(site=s);assert frappe.conf.get('encryption_key');frappe.destroy()"
        run("docker","exec","-u","frappe","-w",BENCH+"/sites",LIVE,BENCH+"/env/bin/python","-B","-c",verify_keys,*shared.SITES)
        manifest = backup_for_activation(shared)
        networks = json.loads(run("docker","inspect","--format","{{json .NetworkSettings.Networks}}",LIVE))
        if len(networks) != 1:
            raise RuntimeError("unexpected_application_network")
        old_jobs = {}
        for site in shared.SITES:
            check = checked_setup(site,"prepare",["docker","run","--rm","--network",next(iter(networks)),"--volumes-from",LIVE,
                "--entrypoint",BENCH+"/env/bin/python","-w",BENCH+"/sites",image,"-B","-c",SCHEMA,site,"prepare"])
            old_jobs[site] = json.loads(check)["existing_job"]
        rc = shared.activate(image, manifest, request["revision"], prepare_runtime=layout.apply,
                             restore_runtime=layout.restore)
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
        layout = RuntimeLayout(candidate, files, data["previous"])
        if data["action"] == "trial":
            # Exercise activation and rollback on a temporary copy of the real Compose input.
            layout.config = tmp / "compose.yaml"
            layout.config.write_bytes(layout.before)
            layout.apply(tmp)
            if layout.config.read_bytes() != layout.after:
                raise RuntimeError("trial_compose_change_failed")
            layout.restore()
            if layout.config.read_bytes() != layout.before:
                raise RuntimeError("trial_compose_restore_failed")
            print("Compose change and rollback verified on a temporary copy", flush=True)
        verify_stage(candidate, files)
        if data["action"] == "publish":
            sys.exit(activate(tmp, data, candidate, files, layout))

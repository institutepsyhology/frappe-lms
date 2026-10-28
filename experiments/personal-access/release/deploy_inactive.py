"""Build and deploy the access feature on the three existing sites.

Run as root from a reviewed git-archive context. Creates fresh database backups,
checks them, migrates each site with the new image, then switches the application
image. The release switch is preserved on each site. Rollback restores the old
image; it does not reverse additive database migrations.
"""

import datetime
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tarfile
import time

ROOT = Path(__file__).resolve().parents[3]
BASE = Path("/opt/company-lms")
OLD = "sha256:6c6e865c6c9165c5292c5c83da784d5840284e00b9355b895f4a42962f966018"
BASE_TAG = "company-lms:lesson-settings-r21-20261028"
BASE_IMAGE = "sha256:4781e698ca6b3b4ed09bbe9af113664887dd7dc17421127e472f80f23f8ab610"
TAG = "company-lms:lesson-menu-r26-20261029"
OVERLAY = ("lms/lms/api.py", "lms/lms/permissions.py", "lms/lms/utils.py",
    "lms/lms/doctype/course_lesson/course_lesson.py", "lms/lms/doctype/course_lesson/course_lesson.json",
    "lms/lms/access_actions.py", "lms/lms/individual_access.py",
    "lms/lms/doctype/lms_access_policy_lesson/lms_access_policy_lesson.json",
    "frontend/src/components/Courses/LessonAccessSettings.vue", "frontend/src/tests/lessonAccessSettings.test.ts",
    "frontend/src/pages/LessonForm.vue")
SITES = ("my-lk.mastervision.su", "my-lk.iomp.ru", "my-lk.mv-centr.ru")
BACKEND = "company-lms-backend-1"

CHECK = r'''
import json, os
os.chdir('/home/frappe/frappe-bench/sites')
import frappe
result=[]
for site in %r:
 try:
  frappe.init(site=site); frappe.connect()
  flag = frappe.conf.get('individual_access_release_enabled') is True
  names = ('LMS Access Grant','LMS Access Grant Lesson','LMS Access Policy','LMS Access Policy Lesson','LMS Lesson Visit')
  result.append({'site':site,'release_enabled':flag,'doctypes':all(frappe.db.exists('DocType', name) for name in names)})
 finally: frappe.destroy()
print('ACCESS_RELEASE_STATE:'+json.dumps(result))
''' % (SITES,)

BACKUP = r'''
import gzip, hashlib, json, os, sys
from pathlib import Path
import frappe
from frappe.utils.backups import BackupGenerator
site, stamp = sys.argv[1:]
frappe.init(site=site); frappe.connect()
try:
 if frappe.db.get_single_value('System Settings', 'encrypt_backup'):
  raise RuntimeError('encrypted backup requires separate verification')
 base = Path('/home/frappe/frappe-bench/sites') / site / 'private' / 'backups'
 target = base / ('access-inactive-' + stamp)
 target.mkdir(mode=0o700)
 c = frappe.conf
 backup = BackupGenerator(c.db_name, c.db_user, c.db_password, db_socket=c.db_socket,
  db_host=c.db_host, db_port=c.db_port, db_type=c.db_type, backup_path=str(target), ignore_conf=True)
 backup.get_backup(ignore_files=True, force=True)
 path = Path(backup.backup_path_db)
 config = Path(backup.backup_path_conf)
 if path.parent != target or config.parent != target or not path.is_file() or not config.is_file():
  raise RuntimeError('backup files missing')
 digest=hashlib.sha256()
 with path.open('rb') as data:
  for chunk in iter(lambda: data.read(1048576), b''): digest.update(chunk)
 with gzip.open(path,'rb') as data:
  while data.read(1048576): pass
 print('SAFE_BACKUP:'+json.dumps({'site':site,'bytes':path.stat().st_size,'sha256':digest.hexdigest()}))
finally:
 frappe.destroy()
'''


def command(args, timeout=120):
    result = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
    if result.returncode:
        raise RuntimeError("command failed: " + " ".join(args[:3]))
    return result.stdout.strip()


def check_sites():
    result = command(["docker", "exec", "-u", "frappe", "-w", "/home/frappe/frappe-bench/sites",
                      BACKEND, "/home/frappe/frappe-bench/env/bin/python", "-c", CHECK], timeout=60)
    rows = [line.removeprefix("ACCESS_RELEASE_STATE:") for line in result.splitlines() if line.startswith("ACCESS_RELEASE_STATE:")]
    if len(rows) != 1:
        raise RuntimeError("cannot verify site configuration")
    return json.loads(rows[0])


def main():
    commit = sys.argv[1]
    if os.geteuid() != 0 or command(["hostname"]) != "spb-3-vm-t6fa" or not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise RuntimeError("unexpected host or source commit")
    spec = importlib.util.spec_from_file_location("release_helpers", ROOT / "russian-deploy.py")
    helper = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(helper)
    if not helper.services_healthy(OLD):
        raise RuntimeError("production image changed since review")
    env = BASE / "runtime/.env"
    original = env.read_bytes()
    lines = re.findall(rb"^LMS_IMAGE=(.+)$", original, re.M)
    if len(lines) != 1 or lines[0].strip().decode() != OLD:
        raise RuntimeError("runtime image changed since review")
    prior_states = check_sites()
    before = helper.snapshot()
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    backup = BASE / "backups" / ("access-inactive-" + stamp)
    backup.mkdir(mode=0o700)
    helper.write_new(backup / "runtime.env.before", original)
    helper.write_new(backup / "site-counts.before.json", (json.dumps(before) + "\n").encode())
    report = {"source_commit": commit, "previous_image": OLD, "backup_directory": str(backup),
              "migrated_sites": [], "release_switches_before": prior_states, "ok": False}
    switched = False
    try:
        if command(["docker", "image", "inspect", BASE_TAG, "--format", "{{.Id}}"] ) != BASE_IMAGE:
            raise RuntimeError("base image is unavailable")
        with tarfile.open(ROOT / "lesson-publication-overlay.tar", "x") as overlay:
            for relative in OVERLAY:
                path = ROOT / relative
                if not path.is_file() or path.is_symlink():
                    raise RuntimeError("missing source file: " + relative)
                overlay.add(path, arcname=relative, recursive=False)
        command(["docker", "build", "--network=none", "--pull=false", "--build-arg", "SOURCE_COMMIT=" + commit,
                 "--tag", TAG, "-f", str(ROOT / "experiments/personal-access/release/Containerfile"), str(ROOT)], timeout=600)
        image = command(["docker", "image", "inspect", TAG, "--format", "{{.Id}}"])
        if not re.fullmatch(r"sha256:[0-9a-f]{64}", image) or image == OLD:
            raise RuntimeError("candidate image is invalid")
        report["image"] = image
        backup_results = []
        for site in SITES:
            result = subprocess.run(["docker", "exec", "-i", "-u", "frappe", "-w", "/home/frappe/frappe-bench/sites",
                BACKEND, "/home/frappe/frappe-bench/env/bin/python", "-c", BACKUP, site, stamp],
                capture_output=True, text=True, timeout=300)
            lines = [line.removeprefix("SAFE_BACKUP:") for line in result.stdout.splitlines() if line.startswith("SAFE_BACKUP:")]
            if result.returncode or len(lines) != 1:
                raise RuntimeError("fresh backup failed for " + site)
            backup_results.append(json.loads(lines[0]))
        report["database_backups_verified"] = True
        report["database_backups"] = backup_results
        networks = json.loads(command(["docker", "inspect", BACKEND, "--format", "{{json .NetworkSettings.Networks}}"] ))
        if len(networks) != 1:
            raise RuntimeError("unexpected application network")
        network = next(iter(networks))
        for site in SITES:
            command(["docker", "run", "--rm", "--network", network, "--volumes-from", BACKEND,
                     "--entrypoint", "bench", "-w", "/home/frappe/frappe-bench/sites", image,
                     "--site", site, "migrate"], timeout=300)
            report["migrated_sites"].append(site)
        temporary = env.with_name(".env.access-" + stamp)
        helper.write_new(temporary, re.sub(rb"(?m)^LMS_IMAGE=.+$", ("LMS_IMAGE=" + image).encode(), original))
        os.replace(temporary, env)
        switched = True
        helper.up()
        deadline = time.monotonic() + 150
        while not helper.services_healthy(image) or not all(helper.ping(site) for site in SITES):
            if time.monotonic() >= deadline:
                raise RuntimeError("new image failed health checks")
            time.sleep(3)
        states = check_sites()
        if any(not row["doctypes"] for row in states) or states != prior_states:
            raise RuntimeError("schema or site release switch verification failed")
        after = helper.snapshot()
        if after != before:
            raise RuntimeError("site counts or languages changed")
        report.update(ok=True, schemas_present=True, counts_and_languages_unchanged=True,
                      sites=states, application_services_healthy=True)
    except Exception as error:
        report["error"] = type(error).__name__
        if isinstance(error, RuntimeError):
            report["detail"] = str(error)
        if switched:
            try:
                temporary = env.with_name(".env.access-rollback-" + stamp)
                helper.write_new(temporary, original)
                os.replace(temporary, env)
                helper.up()
                deadline = time.monotonic() + 150
                while not helper.services_healthy(OLD) or not all(helper.ping(site) for site in SITES):
                    if time.monotonic() >= deadline:
                        raise RuntimeError("rollback health check failed")
                    time.sleep(3)
                report["rolled_back"] = True
            except Exception:
                report["rolled_back"] = False
    report["completed_at_utc"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    helper.write_new(backup / "result.json", (json.dumps(report, ensure_ascii=False, indent=2) + "\n").encode())
    print(json.dumps(report, ensure_ascii=False))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

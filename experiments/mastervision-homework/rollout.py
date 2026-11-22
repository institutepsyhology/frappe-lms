"""From the Windows checkout: trial, or publish after pushing this branch to GitHub."""
import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import shlex
import subprocess

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
PREVIOUS = "7924cbb54ecb434f3dfe633beeb0c493c3484f02"
BRANCH = "feature/course-access-20261117"
UI = "frontend/src/components/Assignment.vue"
PAYLOAD = [
    UI, "lms/hooks.py", "lms/locale/ru.po", "lms/lms/individual_access.py",
    "lms/lms/doctype/course_lesson/course_lesson.py",
    "lms/lms/assignment_answer_files.py", "lms/lms/avo_homework_approval.py",
    "lms/lms/doctype/lms_assignment/lms_assignment.json",
    "lms/lms/doctype/lms_assignment_submission/lms_assignment_submission.json",
    "lms/lms/doctype/lms_assignment_submission/lms_assignment_submission.py",
]
DRIVER = "experiments/mastervision-homework/host.py"
SHARED = ["experiments/private-course-access/release.py",
          "experiments/avo-credential-profiles-interface/prepare_sites.py",
          "experiments/avo-credential-profiles-interface/deploy.py",
          "experiments/mastervision-homework/stage.py"]
TESTS = ["lms/lms/test_assignment_answer_files.py", "lms/lms/test_avo_homework_approval.py",
         "lms/lms/test_optional_assignment_progress.py",
         "lms/lms/doctype/lms_assignment_submission/test_lms_assignment_submission.py",
         "lms/lms/doctype/lms_access_grant/test_lms_access_grant.py"]


def git(*args):
    return subprocess.check_output(["git", "-C", str(ROOT), *args])


def previous_sha(path):
    old = subprocess.run(["git", "show", PREVIOUS+":"+path], cwd=ROOT, capture_output=True)
    return None if old.returncode else hashlib.sha256(old.stdout.replace(b"\r\n", b"\n")).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["trial", "publish"])
    args = parser.parse_args()
    production = args.action == "publish"
    if git("branch", "--show-current").decode().strip() != BRANCH:
        raise ValueError("unexpected_branch")
    rev = git("rev-parse", "HEAD").decode().strip()
    if production:
        url = git("remote", "get-url", "origin").decode().strip().rstrip("/")
        if url.removesuffix(".git") not in ("https://github.com/institutepsyhology/frappe-lms",
                                              "git@github.com:institutepsyhology/frappe-lms"):
            raise ValueError("wrong_publication_remote")
        if git("ls-remote", "--exit-code", "origin", "refs/heads/"+BRANCH).decode().split()[0] != rev:
            raise ValueError("revision_not_published")
        if git("show", rev+":"+DRIVER).replace(b"\r\n", b"\n") != (ROOT/DRIVER).read_bytes().replace(b"\r\n", b"\n"):
            raise ValueError("release_driver_unpublished")
        diff = git("diff", "--name-only", PREVIOUS, rev, "--", "frontend", "lms").decode().splitlines()
        extras = [f for f in diff if f not in PAYLOAD and "/test_" not in f and "/tests/" not in f]
        if extras:
            raise ValueError("unpackaged_application_changes: "+str(extras))
    files = {}
    for f in PAYLOAD + SHARED + TESTS:
        raw = git("show", rev+":"+f) if production else (ROOT/f).read_bytes()
        files[f] = base64.b64encode(raw.replace(b"\r\n", b"\n")).decode()
    data = {"action": args.action, "revision": rev, "files": files, "previous": {f: previous_sha(f) for f in PAYLOAD}}
    # Small source packets only. Builds, assets and backups never touch the laptop.
    ssh = Path(os.environ["SystemRoot"])/"System32/OpenSSH/ssh.exe"
    driver = (ROOT/DRIVER).read_text(encoding="utf-8")
    command = "python3 -B -c " + shlex.quote(driver)
    result = subprocess.run([str(ssh), "-o", "BatchMode=yes", "-o", "IdentitiesOnly=yes", "-o", "ConnectTimeout=15",
        "-o", "StrictHostKeyChecking=yes", "-o", "UserKnownHostsFile="+str(ROOT.parent/"frappe-deploy/known_hosts"),
        "-i", str(Path.home()/".ssh/codex_timeweb_lms_20261010"), "root@89.223.71.30", command],
        input=json.dumps(data).encode(), timeout=3600)
    raise SystemExit(result.returncode)


if __name__ == "__main__":
    main()

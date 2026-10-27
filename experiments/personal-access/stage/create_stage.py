"""Create a separate, private Frappe test stack on the documented LMS host.

Usage: python3 create_stage.py BUNDLE_TAR COMMIT_SHA
The bundle is produced from tracked LMS source. No production volumes, networks,
ports, databases, credentials or site directories are used. This script does not
remove previous containers or files. It fails if its deterministic names exist.
"""

import json
import os
from pathlib import Path
import re
import secrets
import subprocess
import sys
import time

BASE = Path("/opt/company-lms")
STAGE = BASE / "access-stage-20261027"
NETWORK = "company-lms-access-stage-20261027"
DB = "company-lms-access-stage-db-20261027"
CACHE = "company-lms-access-stage-cache-20261027"
QUEUE = "company-lms-access-stage-queue-20261027"
APP = "company-lms-access-stage-app-20261027"
IMAGE = "sha256:d7ee1478951488710ff2c577f2e5c3d199a241a84836272e2896abbe1cf5ae99"
SITE = "access-stage.local"


def run(*command, timeout=120):
    result = subprocess.run(command, capture_output=True, text=True, timeout=timeout)
    if result.returncode:
        # Diagnostics are kept private: a subprocess may include a generated password.
        (STAGE / "error.log").write_text(result.stdout + "\n" + result.stderr, encoding="utf-8")
        raise RuntimeError("stage command failed; private diagnostics retained")
    return result.stdout.strip()


def main():
    if os.geteuid() != 0 or run("hostname") != "spb-3-vm-t6fa":
        raise RuntimeError("unexpected host or account")
    bundle = Path(sys.argv[1]).resolve(strict=True)
    commit = sys.argv[2]
    if not re.fullmatch(r"[0-9a-f]{40}", commit) or not bundle.is_file():
        raise RuntimeError("invalid source bundle or commit")
    if STAGE.exists():
        raise RuntimeError("stage directory already exists; preserve it")
    for name in (NETWORK, DB, CACHE, QUEUE, APP):
        result = subprocess.run(["docker", "inspect", name], capture_output=True)
        if result.returncode == 0:
            raise RuntimeError("a stage resource already exists; preserve it")
    STAGE.mkdir(mode=0o700)
    db_password = secrets.token_urlsafe(32)
    admin_password = secrets.token_urlsafe(32)
    # Only stage-specific credentials; never copied to the source repository.
    secret_path = STAGE / "credentials.json"
    descriptor = os.open(secret_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w") as stream:
        json.dump({"database": db_password, "administrator": admin_password}, stream)
    run("docker", "network", "create", "--internal", NETWORK)
    run("docker", "run", "-d", "--name", DB, "--network", NETWORK, "--network-alias", "db",
        "-e", "MARIADB_ROOT_PASSWORD=" + db_password, "mariadb:11.8",
        "--character-set-server=utf8mb4", "--collation-server=utf8mb4_unicode_ci")
    for name, alias in ((CACHE, "redis-cache"), (QUEUE, "redis-queue")):
        run("docker", "run", "-d", "--name", name, "--network", NETWORK, "--network-alias", alias,
            "redis:7.4-alpine")
    run("docker", "run", "-d", "--name", APP, "--network", NETWORK,
        "--entrypoint", "sleep", IMAGE, "infinity")
    stage_mounts = json.loads(run("docker", "inspect", APP, "--format", "{{json .Mounts}}"))
    production_mounts = json.loads(run("docker", "inspect", "company-lms-backend-1", "--format", "{{json .Mounts}}"))
    if {item["Source"] for item in stage_mounts} & {item["Source"] for item in production_mounts}:
        raise RuntimeError("stage shares a production mount")
    run("docker", "cp", str(bundle), APP + ":/tmp/access-source.tar")
    run("docker", "exec", "-u", "frappe", APP, "tar", "-xf", "/tmp/access-source.tar",
        "-C", "/home/frappe/frappe-bench/apps/lms")
    deadline = time.monotonic() + 90
    while subprocess.run(["docker", "exec", DB, "mariadb", "-uroot", "-p" + db_password, "-e", "SELECT 1"],
                         capture_output=True).returncode:
        if time.monotonic() >= deadline:
            raise RuntimeError("isolated database did not start")
        time.sleep(2)
    prefix = ["docker", "exec", "-u", "frappe", "-w", "/home/frappe/frappe-bench/sites", APP, "bench"]
    run(*prefix, "new-site", SITE, "--db-host", "db", "--db-root-password", db_password,
        "--mariadb-user-host-login-scope", "%", "--admin-password", admin_password,
        "--install-app", "payments", "--install-app", "lms", timeout=600)
    run(*prefix, "--site", SITE, "set-config", "redis_cache", "redis://redis-cache:6379")
    run(*prefix, "--site", SITE, "set-config", "redis_queue", "redis://redis-queue:6379")
    run(*prefix, "--site", SITE, "set-config", "allow_tests", "True", "--parse")
    report = {"site": SITE, "source_commit": commit, "image": IMAGE, "network": NETWORK,
              "internal_network": True, "production_volumes_mounted": False, "installed": True}
    (STAGE / "stage.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report))


if __name__ == "__main__":
    main()

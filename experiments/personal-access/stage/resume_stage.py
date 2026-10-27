"""Create a second isolated site after an interrupted initial setup, preserving the first."""

import json
import os
from pathlib import Path
import secrets
import subprocess

STAGE = Path("/opt/company-lms/access-stage-20261027")
APP = "company-lms-access-stage-app-20261027"
DB = "company-lms-access-stage-db-20261027"
SITE = "access-stage2.local"


def run(command, timeout=120):
    result = subprocess.run(command, capture_output=True, text=True, timeout=timeout)
    if result.returncode:
        path = STAGE / "resume-error.log"
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w") as stream:
            stream.write(result.stdout + "\n" + result.stderr)
        raise RuntimeError("test site creation failed; private diagnostics retained")
    return result.stdout.strip()


def main():
    if os.geteuid() != 0 or run(["hostname"]) != "spb-3-vm-t6fa" or not STAGE.is_dir():
        raise RuntimeError("unexpected host or missing stage")
    check = subprocess.run(["docker", "exec", APP, "test", "-e", "/home/frappe/frappe-bench/sites/" + SITE])
    if check.returncode == 0:
        raise RuntimeError("second site already exists; preserve it")
    db_password = run(["docker", "exec", DB, "printenv", "MARIADB_ROOT_PASSWORD"])
    admin_password = secrets.token_urlsafe(32)
    descriptor = os.open(STAGE / "second-site-admin.json", os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w") as stream:
        json.dump({"administrator": admin_password}, stream)
    run(["docker", "exec", DB, "mariadb", "-uroot", "-p" + db_password, "-e", "SELECT 1"])
    prefix = ["docker", "exec", "-u", "frappe", "-w", "/home/frappe/frappe-bench/sites", APP, "bench"]
    run(prefix + ["new-site", SITE, "--db-host", "db", "--db-root-password", db_password,
                  "--mariadb-user-host-login-scope", "%", "--admin-password", admin_password,
                  "--install-app", "payments", "--install-app", "lms"], timeout=600)
    run(prefix + ["--site", SITE, "set-config", "redis_cache", "redis://redis-cache:6379"])
    run(prefix + ["--site", SITE, "set-config", "redis_queue", "redis://redis-queue:6379"])
    run(prefix + ["--site", SITE, "set-config", "allow_tests", "True", "--parse"])
    report = {"site": SITE, "installed": True, "production_volumes_mounted": False}
    (STAGE / "second-site.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report))


if __name__ == "__main__":
    main()

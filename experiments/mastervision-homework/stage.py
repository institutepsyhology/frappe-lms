"""Read only test sources on stdin; exercise the actual candidate inside the isolated stage."""
import base64
import json
from pathlib import Path
import subprocess
import sys
import unittest

import frappe
from frappe.tests.utils import toggle_test_mode

SITE = "access-stage2.local"
frappe.init(site=SITE, sites_path="/home/frappe/frappe-bench/sites")
if frappe.local.site != SITE or not frappe.conf.allow_tests or frappe.conf.db_host != "db":
    raise RuntimeError("isolated_stage_required")
app = Path("/home/frappe/frappe-bench/apps/lms")
for line in Path("/proc/self/mountinfo").read_text().splitlines():
    mount = Path(line.split()[4])
    if mount != Path("/") and (mount == app or mount in app.parents or app in mount.parents):
        raise RuntimeError("stage_app_must_be_disposable")
for name, data in json.load(sys.stdin).items():
    target = (app / name).resolve()
    if not target.is_relative_to(app/"lms/lms") or not target.name.startswith("test_") or target.suffix != ".py":
        raise ValueError("wrong_test_file")
    target.write_bytes(base64.b64decode(data, validate=True))
frappe.connect()
try:
    toggle_test_mode(True)
    frappe.set_user("Administrator")
    # Run both phases of the very same schema and scheduler setup as publish.
    for action in ("prepare", "enable"):
        subprocess.run([sys.executable, "-B", "-c", sys.argv[1], SITE, action], check=True)
    frappe.clear_cache()
    frappe.db.commit()
    tests = ["lms.lms.test_assignment_answer_files", "lms.lms.test_avo_homework_approval",
             "lms.lms.test_optional_assignment_progress",
             "lms.lms.doctype.lms_assignment_submission.test_lms_assignment_submission.TestLMSAssignmentSubmission.test_optional_file_follows_submission_read_permissions"]
    actual = unittest.defaultTestLoader.loadTestsFromNames(tests)
    result = unittest.TextTestRunner(verbosity=1).run(actual)
    if not result.wasSuccessful() or result.testsRun < 13:
        raise SystemExit(1)
finally:
    frappe.db.rollback()
    frappe.clear_cache()
    frappe.destroy()

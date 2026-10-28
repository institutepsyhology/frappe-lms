"""Enable the access feature on the three LMS sites after an authorized release.

The switch by itself does not enable a course policy. Existing site configuration
and database backups must be made before running; course policies are configured
separately by an administrator. Run on the LMS host, not on a local checkout.
"""

import subprocess

SITES = ("my-lk.mastervision.su", "my-lk.iomp.ru", "my-lk.mv-centr.ru")
SERVICES = ("backend", "frontend", "websocket", "queue-short", "queue-long", "scheduler")
BACKEND = "company-lms-backend-1"

for site in SITES:
	subprocess.run(["docker", "exec", "-u", "frappe", "-w", "/home/frappe/frappe-bench/sites",
		BACKEND, "bench", "--site", site, "set-config", "individual_access_release_enabled", "True", "--parse"], check=True)

subprocess.run(["docker", "compose", "--project-directory", "/opt/company-lms/runtime", "--profile", "jobs",
	"restart", *SERVICES], check=True)
print("Site access switches enabled. Individual course policies remain separate.")

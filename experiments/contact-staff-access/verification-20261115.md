# Production verification, 15 November 2026

Application source revision: `90cbdd59881490c4cb659987133bf474b50cd444`.
Running image:
`sha256:d588adfe762bd7fb29a2f97a588563cb46f734682e14172df837caba07ab05cb`.
It retains the pinned first 50 layers plus one overlay layer (51 total), with
runtime user `frappe`. The release wrapper checked all manifest file hashes.

All three shared-image sites passed additive schema setup, six-service image
health checks, non-decreasing User/Contact/course/lesson/enrollment counts and
HTTP pings. Existing encryption keys were preserved. Fresh database/key backups
were verified privately before activation. No positions were auto-assigned.

The final candidate passed the 120 Python and 67 frontend checks plus all three
real-controller/MariaDB smoke suites. The roster fixture contained 205 learners.
Synthetic stage fixtures and source captures were not copied to production.

Actual native MVC MCP checks after activation:

- Contact capability and staff-position metadata endpoints respond correctly.
- Unified contact directory returns a bounded page of 50 records.
- Numeric imported-contact resolution and the common card work; the basic
  card response does not return a password value.
- A real course with 2,637 students returns 50 rows and correct total, with
  contact fields and per-person access metadata. Consecutive pages do not
  overlap. The shared access-detail read succeeds for a real enrolled student.

An authenticated server-context check as the existing moderator confirmed:
own-role controls are disabled, direct self-role change is rejected before
write, and the persisted roles are unchanged. No production password/email or
membership change was performed for verification.

The source branch was read back from GitHub and matched the application source
revision above before this documentation-only receipt. The image still points
to that tested application revision; this receipt does not require a rebuild.
Unrelated local lesson-order prototypes and an unrelated editor test remain
outside the published changes and running image.

Visual browser interaction was unavailable in this session. These results
prove component tests, stored data, server/controller behavior and actual MCP,
not a manual visual review of the deployed pages.

Entry points on each site's `/lms` application:

- `/contact-directory` — unified contacts;
- `/staff/positions` — position hierarchy and supported action matrix;
- `/staff/employees` — bounded employee assignments;
- course dashboard pencil — one student's course and lesson access.

The supported capability resources are contacts, course access, staff,
positions and credentials. Existing native LMS author roles remain distinct;
this release does not reproduce all 82 source-platform resource groups.

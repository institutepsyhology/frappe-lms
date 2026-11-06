# Titles up to 512 characters with safe HTML

Work in progress; backend and frontend releases are independent. Course and lesson title Data
fields are widened to 512 characters of stored markup. The migration
`lms.lms.avo_title_schema.execute` is site-scoped, rejects conflicting property
setters, widens only the two title columns, and requires verified backups.
Long imported course titles receive a deterministic account-scoped internal
name; source IDs and full source snapshots remain unchanged.
The migration also widens the LMS fields that fetch a course or lesson title,
including Course Chapter.course_title. Without this, Frappe rejects creating
a chapter for a course whose title exceeds 140 characters.

The frontend allows formatting and links in title views, safely removes active
markup and unsafe styles, and uses plain title text in breadcrumbs and browser
metadata. Navigational cards show formatted link text without nesting links.
Headings in lessons retain safe formatted links. Frontend tests and isolated
Vue compilation do not prove that production assets have been built or
deployed. Rendering and access checks remain required. The previous full Vite
build exhausted the 3 GiB Node heap; use a verified lower-memory build strategy
or suitable separate builder, not an unbounded build on the production host.

On the isolated `access-stage2.local` site, the widening migration was run
twice, both 512-character values were accepted and 513 rejected, and synthetic
course and lesson HTML titles of exactly 512 characters were inserted and
read back inside rolled-back transactions. The production database was not
changed by those tests. The backend release procedure is `title-512/deploy_backend.py`;
it builds one layer, checks its files, verifies all-site backups, switches with
rollback, and widens columns without ever shrinking them on error. Do not run
while a batch importer is writing. Recheck the active image and test through
the actual Codex MCP after release. The frontend build and visual checks remain
separate and the backend release alone does not make formatted titles visible.

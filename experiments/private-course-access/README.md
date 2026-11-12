# Private imported course access

Imported courses remain unpublished and unavailable for self-enrollment. The
frontend permits an existing entitled student to open a private course; an
unassigned user still receives no course/lesson access. Personal dates, freezes,
and exact lesson assignments are enforced by the existing server access policy.

## Data operator

`enable_imported_access.plan(frappe)` is read-only. The separate trusted Bench
operator `apply(frappe, journal_callback, limit=None)` disables self-enrollment
for imported MVC courses and enables only lessons referenced by owned Active
native grants matching their Applied migration ledger and source identity.
It requires Administrator, the release flag, the Moscow site clock, and the
unchanged strict migration policy. Known source drafts can be explicitly held
with `known_source_draft_ids`; unreferenced lessons remain drafts.

Courses retain `published=0`; no grants, enrollments, content, source IDs, or
lesson allowlists are changed. Publication uses the guarded document action,
audience `All`, no preview, and the existing publication date (or the current
time if absent). Each document has a private, acknowledged before/after flag
journal, content hash checks, commit/read-back, and idempotent resumption.

**Do not call public `publish_lesson(..., All)` for this migration.** That action
adds the lesson to other grants and can broaden the existing personal lesson
lists. `Future Only` would exclude students who enrolled before publication.
The regular importer still requires draft migration staging; its draft guard
has deliberately not been relaxed. Subsequent content refreshes need a separate
explicit path for already active lessons.

Run the synthetic operator tests without Frappe or private data:

```sh
python -m unittest discover -s experiments/private-course-access -p 'test_enable_imported_access.py'
python -m unittest discover -s experiments/private-course-access -p 'test_release.py'
```

## Reproducible frontend-only release

The Dockerfile literally pins baseline
`sha256:d4a1f221ed802b0625963909334c067d0ba6f164563193519416537e8d9b2d8d`.
Its nine source files are `CourseDetail.vue`, `Courses.vue`, their required
`safeHtmlLevels.ts` directive (including `titleText`), and six frontend regression
tests. The pinned baseline already has identical `safeUrl.ts`, `safeHtml.ts`,
and DOMPurify 3.2.6, so no dependency changes are required. It runs the tests and
one Vite build with a 4096 MB Node heap. No Python
application files, database schema changes, or unrelated editor tests enter
this overlay.

Commit and publish the reviewed source first. Create the context outside the
checkout; it reads those nine files and the Dockerfile from the specified Git
commit, never arbitrary working files or private exports:

```sh
python experiments/private-course-access/create_context.py /tmp/private-course-access-context --revision HEAD
docker build -t company-lms:private-course-access /tmp/private-course-access-context
docker image inspect company-lms:private-course-access --format '{{.Id}}'
```

Use the returned immutable image ID, not the mutable tag, for activation.
`source-manifest.json` records the commit, baseline and every source/context
hash. The context pins the image revision label to that commit by default.

On the existing LMS host, as root, with **all bulk writers finished or paused**
and other deployment tools idle:

```sh
python experiments/private-course-access/release.py prepare
python experiments/private-course-access/release.py activate sha256:CANDIDATE \
  --backup-manifest /opt/company-lms/backups/contact-card-TIMESTAMP/manifest.json \
  --source-revision COMMITTED_40_CHARACTER_SHA
```

Preparation reuses the existing direct backup generator, verifies gzip CRCs,
and saves private database/config/key backups for all three sites without
deleting older backups. Activation requires this release's explicit latest
manifest, age at most two hours, private root-owned files, matching file sizes
and streaming hashes, and candidate image provenance labels.

The existing activation helper then rechecks the exact baseline and runtime
image, replaces all six LMS service images, clears site caches only, checks site
record counts and three HTTPS pings, and rolls the runtime image back on failure.
It never restores/deletes databases. The helper writes its private activation
report under `/opt/company-lms/backups/contact-card-deploy-*`.

Activation restarts backend/queue containers and would interrupt an attached
data operator; do not activate while it is running. The local release lock
serializes this helper, not other release tools. After activation, verify actual
allowed/denied student HTTP behavior separately (`http_probe.py`); image health
and stored grants alone do not prove frontend or authorization behavior.

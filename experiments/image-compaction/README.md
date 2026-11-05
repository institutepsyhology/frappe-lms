# Guarded Frappe image compaction

The current release is close to the host's overlay layer limit. This experiment
prepares a one-layer candidate from the exact installed image, without switching
production. It creates a fresh stopped container from the image, covers the two
declared site/log volume locations with empty tmpfs mounts, exports the image
filesystem, and assembles a single-layer OCI image while preserving the image's
configuration and platform. It never exports the running container or any site
volume.

The candidate is accepted only if the complete image configuration matches,
every exported filesystem entry and file hash matches, the platform matches,
the image has exactly one layer, and application imports succeed in an isolated
container. It checks source and running-image identities and free disk space and
refuses an existing candidate tag. Temporary files are private on the server.
The candidate is not deployed by this script.

If OCI import creates a candidate but Docker does not immediately resolve its
tag, do not overwrite any tag or switch services. Verify the image by its exact
ID and configuration, assign a separate unused test tag, and run
`verify_candidate.py` to resume the file-by-file comparison. Its image IDs and
tag are pinned to this observed test, and it streams both filesystem exports
into a private temporary index; it does not read production volumes.

If the strict comparison reports a mismatch, `diagnose_candidate.py` repeats
the isolated comparison and reports only difference categories and hashed path
examples. Do not use the candidate for production until every difference has
been explained and the verification strategy has been revised and rerun.

On 2026-11-05 the strict comparison found only `mtime` differences for the
directory entries `dev/pts` and `dev/shm`. Two independently created containers
from the same source image confirmed that Docker generates these timestamps per
container. The comparison now ignores only those two directory timestamps;
their type, permissions, ownership, xattrs and all other fields remain checked.
No other path or file timestamp is exempted. Re-run the full comparison before
using the candidate.

Run `python experiments/image-compaction/test_compaction.py` before publishing.
Production switching is a separate guarded release requiring fresh backups,
health checks on all three sites, unchanged site state, rollback, actual MCP
verification, and a published matching commit. Subsequent releases must start
from a pinned compacted baseline and include every relevant source change, not
stack new releases on the previous one indefinitely.

`deploy.py` implements the guarded switch for the specific image IDs pinned
in this experiment. It reruns the entire comparison immediately before the
switch, verifies fresh database backups, saves the original runtime settings,
and rolls back if service, site, count, language, or release-setting checks
fail. It changes no lesson or course data. It is deliberately pinned and must
not be reused with different images without a new review and verification.

For later changes limited to the three AVO backend modules, the reviewed
`Backend.Containerfile` gives every build the same verified one-layer parent
and copies all three current modules together. Build only from a reviewed Git
commit, verify module hashes and tests in the resulting image, and use a guarded
release with fresh backups and rollback. This does not cover frontend assets,
schema changes, other backend modules or changes made outside that commit: for
those, explicitly include and verify every affected artifact. Do not replace a
running image with a partial overlay or assume this file covers every update.

On 2026-11-05 the compact image was verified against 141,554 filesystem
entries and installed on all three sites with verified database backups,
unchanged counts/languages/access settings, service checks, and MCP checks.
The following AVO heading release was rebuilt from that compact base with one
additional layer and passed the AVO unit tests, backup and health checks. A
read-only MCP import preview accepted a heading and reported its mismatched
source setting. This does not establish full support for AVO columns, spacers,
responsive layout, or browser rendering; those remain separate work.

The 2026-11-05 spacer release is prepared and tested but not installed.
The frontend unit test passed in an isolated container and the backend suite
passed, but a full Vite build exhausted its 2 GiB and then 3 GiB Node heaps
while the production services remained on the previous release. A separate
2 GiB trial with minification disabled failed as well. Disabling minification
alone is therefore not a demonstrated solution. The private server build log
for the 3 GiB attempt is stored with its guarded release report under
`/opt/company-lms/backups/avo-mcp-20261105T122827225846Z/`. Before retrying,
investigate a genuinely lower-memory build or an appropriate separate builder,
and compare and validate all frontend artifacts. Do not permit spacer imports
without installing and testing the matching frontend renderer.

The backend-only layout guard was installed from commit `3a1e109d` with a
fresh verified backup and rollback checks. Actual MCP dry-runs confirmed that
ordinary multi-column layouts are rejected rather than silently flattened, and
that recognized spacers are rejected with `spacer_renderer_not_installed`
until the matching frontend renderer is installed. The three MCP connections
responded after release. The guarded importer must remain in place until the
full frontend release and its rendering checks have succeeded.

The next guarded backend overlay adds narrowly validated static AVO HTML,
recognition of two identical video slots, and the owner-confirmed choice for
one exact concatenated source field. Source HTML and the original video field
remain in the private snapshot. Unknown HTML, forms, unsupported layouts and
unconfirmed video combinations still stop import; an HTML frame remains subject
to a separate visual check.

On 05.11.2026 that overlay was deployed from commit `75ed0219`: all 41 AVO
tests passed, backups for all three sites were verified, services remained
healthy, and the actual mv-centr MCP preview confirmed the owner-selected video.
The image was rebuilt from the one-layer baseline, not stacked on prior releases.

For two specifically identified and hash-checked source lessons, the owner chose
to retain assignment text while omitting the empty answer form for now. The
converter strips only that verified empty form, keeps the remaining HTML and
original private snapshot, and emits a warning. Changed snapshots, nonempty
forms and unapproved forms remain blocked. Empty answer placeholders are
accepted only when they contain no answer text or links; this avoids copying
student responses into course material.

Deployed from commit `be712f47` on 05.11.2026 with 44 AVO tests, verified
database backups, and healthy services. Actual mv-centr MCP previews for both
approved lessons confirmed that only the assignment text will be imported and
the omission is recorded as a warning. The original snapshots stay private.

The owner requested sequential single-column output only for two identified
mv-centr lessons. Tests check account/course/lesson isolation and confirm all
50 video pairs in each saved snapshot retain their order and both sources.
An exact known inert clipboard stylesheet is preserved; other stylesheets and
unapproved multi-column layouts remain blocked. Visual rendering and playback
still require separate verification.

On 06.11.2026 the inactive overlay fix from `f90438bc` passed 47 tests and
was deployed with verified backups. Actual MCP checks confirmed that a valid
disabled overlay is accepted and an enabled one remains blocked for review.
All three MCP connections responded after deployment.

On 06.11.2026 the single-column overlay was deployed from `ff0c1af1` after
46 AVO tests and verified backups. Both selected lessons were created as drafts;
independent MCP read-back confirmed exactly 50 video pairs per lesson and
byte-for-byte equality of source addresses and their order. Playback and visual
presentation remain unverified. No other lesson was authorized for flattening.
# Google Drive media in reviewed AVO lessons, 2026-11-06

The converter accepts only a constrained Google Drive preview iframe and
transfers two owner-reviewed legacy audio fields as ordinary file links outside
the sandboxed frame. The audio decisions are limited by account, course,
lesson, and source digest; an altered field is stopped for review. The original
snapshot is preserved, as are distinct links and their order. Other unknown
embeds remain blocked. Actual file availability can change, and preview
rendering and playback require independent checks. The guarded release uses
`deploy_drive_media.py`, the same verified single-layer base and rollback
checks as the preceding release. Real source HTML and file URLs stay private.

# Drive media release verification, 2026-11-06

The guarded release from commit `b40093a6` produced image
`sha256:a35468a9202baba5982e0ff591663f2f4b70b1061ec591ea52f3b7ed6383d7dd`.
Its 49 candidate tests and backup integrity checks passed; all three sites
were healthy and their counts and release switches were unchanged. Actual MCP
dry-runs accepted the three reviewed source lessons, while retaining warnings
that frame rendering has not been verified. Backups were not restore-tested.
The follow-up `deploy_drive_media_batch.py` also covers additional individually
verified audio fields and reviewed inert formatting. Unknown files and formats
continue to stop for review.
# Additional Drive audio release verification, 2026-11-06

Commit `a2a69e67` produced image
`sha256:acd943046b5b42c98e83511cd4bd34b2f71a43a7115355c1d78cfeaef71d4f56`.
Candidate tests, backup integrity checks and health checks passed; all three
sites retained their counts and release switches during deployment. The
reviewed audio sources are still matched by account, lesson and digest.
File-page access was checked when reviewed, not continuously. Backups were
not restore-tested; frame rendering and audio playback require visual checks.
# Reviewed HTML and image, 2026-11-06

The converter admits constrained static CSS float values and preserves reviewed
HTML in private lesson snapshots. The user approved a single image-and-text
section in one lesson to be flattened; the decision is bound to the account,
course, lesson and complete section digest. That lesson's validated separators
use sandboxed HTML frames until the native renderer is deployed; exact spacing
needs visual verification. The batch client can send a locally prepared image
only after checking both its source and content digests. The source image itself
is private and is not included in this repository. Unknown images and changed
sections remain blocked. Deploy with `deploy_reviewed_html.py` after publishing
the matching commit and record checks afterwards.

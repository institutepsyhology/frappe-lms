# Backend-only AVO MCP release

This release overlays only `lms/lms/avo_import.py` and `lms/lms/avo_transform.py` onto the exact, verified current LMS image. It does not change dependencies, frontend assets, configuration, databases or site schemas. A prior compatible set of source-ID fields must exist on the intended site.

Prepare a clean `git archive` from a reviewed published commit. Run the module unit tests first; supply this archive and its matching full commit ID to the deployment host. Copy no local exports, personal data, credentials, or video URLs into the archive. Run `python3 experiments/avo-mcp/deploy.py COMMIT` as root from the extracted archive root, retaining its output. The script refuses a changed current runtime image or malformed source commit. It validates the two copied source SHA-256 hashes in the built image, takes fresh integrity-checked database backups, preserves the runtime environment root-only, switches the six existing app services, and verifies all three sites and their counts/language. The previous image and environment are retained for rollback. The script does not migrate schemas.

The build uses a single new filesystem layer: the existing runtime has many
layers and a larger overlay failed to start. Before any switch the deploy
script starts the candidate in isolation and runs the synthetic tests using a
read-only bind mount; a mount or test failure stops deployment.

The script records a root-only deployment result; integrity-checking a backup is not proof of restore. After deployment, verify the intended method through the actual authenticated Codex MCP transport on each relevant site, run dry-run and account-isolation tests, and record safe results in GitHub. Real contents and image bytes stay outside the repository. Keep courses unpublished and lessons as drafts during verification.

## Isolated stage check, 2026-11-03

Commit `6bc27b42` was exercised on a separate test site with synthetic data.
The dry run wrote no records; one draft course and lesson were created with
matching source IDs, a synthetic video pair, a private image and a private
source snapshot. An identical retry succeeded without duplication, a changed
retry was rejected, and no enrollment was created. Guest access was denied
both to the importer and to the private image. These checks do not prove browser
playback, screenshot rendering or backup restore.

## Deployment and live verification, 2026-11-03

Source commit `25712d6b1c57bb3625b0e681a8f8d72dc62b900c` produced image
`sha256:3ee9ef7f61c0d9d1a24a0a6b4b59960b78274600a765af75a9a69e9eb9b01b39`
from previous image `sha256:d985d00e9ce5d032baf77aa8d5cdd6508a22b4194a66a600ba962c526c5ac94a`.
Source digests matched the published commit. The candidate started and passed
14 synthetic tests; fresh database backups passed gzip integrity checks; all
six services and three sites were healthy and counts, languages and access
release switches were unchanged during deployment. This does not prove backup
restore. The earlier multi-layer candidate was not installed because it could
not start; the successful release uses one new filesystem layer.

Through the authenticated Codex MCP on the intended site, the new method was
discovered and its dry-run checked on real AVO data. One course and lesson were
created as drafts, source IDs and both original video pairs were read back, a
private source snapshot was confirmed, and an identical retry returned
`already_imported`; a modified retry was rejected. A synthetic image passed
MCP dry-run. Cross-account input to another site was rejected. A source with
unsupported HTML was reported as `ready=false` without creating a lesson.
An authenticated learner-view screenshot/player check is still outstanding.

The four AVO identity fields were independently created through native MCP on
the Master Vision site as well as on mv-centr. A synthetic dry-run on Master
Vision passed with its own source origin; no Master Vision lesson was created.
IOMP has no verified AVO source mapping and the import method rejects it.

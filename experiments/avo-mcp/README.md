# Backend-only AVO MCP release

This release overlays only `lms/lms/avo_import.py` and `lms/lms/avo_transform.py` onto the exact, verified current LMS image. It does not change dependencies, frontend assets, configuration, databases or site schemas. A prior compatible set of source-ID fields must exist on the intended site.

Prepare a clean `git archive` from a reviewed published commit. Run the module unit tests first; supply this archive and its matching full commit ID to the deployment host. Copy no local exports, personal data, credentials, or video URLs into the archive. Run `python3 experiments/avo-mcp/deploy.py COMMIT` as root from the extracted archive root, retaining its output. The script refuses a changed current runtime image or malformed source commit. It validates the two copied source SHA-256 hashes in the built image, takes fresh integrity-checked database backups, preserves the runtime environment root-only, switches the six existing app services, and verifies all three sites and their counts/language. The previous image and environment are retained for rollback. The script does not migrate schemas.

The script records a root-only deployment result; integrity-checking a backup is not proof of restore. After deployment, verify the intended method through the actual authenticated Codex MCP transport on each relevant site, run dry-run and account-isolation tests, and record safe results in GitHub. Real contents and image bytes stay outside the repository. Keep courses unpublished and lessons as drafts during verification.

## Isolated stage check, 2026-11-03

Commit `6bc27b42` was exercised on a separate test site with synthetic data.
The dry run wrote no records; one draft course and lesson were created with
matching source IDs, a synthetic video pair, a private image and a private
source snapshot. An identical retry succeeded without duplication, a changed
retry was rejected, and no enrollment was created. Guest access was denied
both to the importer and to the private image. These checks do not prove browser
playback, screenshot rendering or backup restore.

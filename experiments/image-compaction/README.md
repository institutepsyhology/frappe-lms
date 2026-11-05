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

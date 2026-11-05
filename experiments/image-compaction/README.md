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

Run `python experiments/image-compaction/test_compaction.py` before publishing.
Production switching is a separate guarded release requiring fresh backups,
health checks on all three sites, unchanged site state, rollback, actual MCP
verification, and a published matching commit. Subsequent releases must start
from a pinned compacted baseline and include every relevant source change, not
stack new releases on the previous one indefinitely.

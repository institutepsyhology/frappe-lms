# AVO legacy labelled video pairs

An AVO lesson sometimes has a main video and an alternative as separate blocks,
each preceded by an explicit Russian label. The converter combines the exact
labelled sequence into one player, retains both original URLs and the main
provider, and flags unmatched or modified labels for review. Pairing is limited
to one APE section. Unlabelled independent videos are not paired. Layout and
label reconstruction differences are warnings.

The account and origin are checked against the Frappe site; IOMP is accepted
only on `my-lk.iomp.ru`. An IOMP release also requires the same AVO ID fields as
the other sites; create/verify them separately and do not grant learner access.
Images from APE require supplied, validated private image bytes; the server
never fetches arbitrary source URLs. Source snapshots remain private.

Run `python -m unittest lms.lms.test_avo_transform lms.lms.test_avo_import_unit`
and verify a representative private source locally. Run the release from a
reviewed, published commit archive, without snapshots or private URLs.
`deploy.py` checks the installed production image, the separate base image,
builds a single-layer overlay, tests it in isolation, backs up all sites,
checks health and unchanged site counts, and rolls back on failure. After
release verify the actual MCP transport, isolation, dry-run and browser player.
Document any limitations and the matching released commit in this repository.

## Release verification, 2026-11-03

Published source `ac74d8b6ea4c9a5dd91c4f8c3bae247e9f8c5dde` produced image
`sha256:3d777da4a1255e0027aa50d8f164918ddc08eab0bef0640c873c3e7d766d1243`.
The candidate passed 21 synthetic backend tests. Integrity checks passed on
fresh database backups; six application services and three sites were healthy,
with unchanged site counts, language, and access-release switches. A backup
integrity check does not demonstrate a restore.

The four identity fields in `lms/lms/avo_mapping_fields.py` were created and
read back on IOMP through its MCP. Synthetic labelled-pair dry runs through the
actual Codex MCP succeeded independently on IOMP, mv-centr and Master Vision.
Synthetic inputs with mismatched IOMP/mv-centr origins were rejected. A changed
label returned `legacy_player_pair_unresolved` and `ready=false`. No real
IOMP lesson or access grant was created by these checks. An IOMP example passed
local conversion using a placeholder for its image, with both original video
URLs retained in one pair. Actual image transfer and playback remain unverified.

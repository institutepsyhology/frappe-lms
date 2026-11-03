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

# MV-Centr API archive and learner-link preservation

These are local read-only collection utilities. They do not import into Frappe,
change credentials/roles/accesses or redeem personal links. Actual learner/staff
session isolation remains a separate implementation phase.

## Confirmed source defect

The old contacts list repeats the last contact's personal link across each
page. Only 2,139 of 213,874 row/link associations match. Other checked contact
fields do not show that defect; full archive/profile/password preservation
checks passed. Three fresh individual-card requests produced three correctly
associated links. See the dated verification and API-data audit reports here.

## Current utilities

- `audit_legacy_links.py --database <contacts.sqlite>`: offline, query-only
  ownership/format/collision audit. Aggregate output only; code 1 means unsafe
  associations were found, not that the audit itself failed.
- `collect_personal_links.py --source-database <old contacts.sqlite>
  --output-directory <new private folder>`: masked-key three-card preflight.
- `collect_personal_links_bulk.py --account mv-centr --source-database
  <IDs contacts.sqlite> --output-directory <private folder>`: resumable
  individual-card link collection. Optional `--seed-database <three-card DB>`
  and `--refresh` (append fresh versions). Core default: one request/second;
  `--requests-per-second` accepts a bounded ceiling up to five/second.
- `legacy_api_snapshot.py --output-directory <private folder> --collect-links`:
  GUI collection of the 26 documented legacy resources available to the key,
  followed by individually verified learner links. One masked GET key remains
  in the process's memory for both phases; there is no secret command argument
  or environment variable. The GUI shows the current resource and link progress.
  Its link phase starts at a three-request/second ceiling, automatically reduced
  on network/throttling/server errors. This is a client setting, not a statement
  of the provider's guaranteed throughput or quota.

Use the existing local Python runtime with Tk/Windows DPAPI. Start a GUI process
with a hidden console. New output folder = new snapshot; same folder = resume.
Keep output outside Git. Never use drive D (the owner's recovery volume).

## Files and status

The snapshot's `snapshot.sqlite` contains compressed DPAPI-encrypted original
responses and versioned source evidence. Its `contacts.sqlite` contains only
numeric source IDs and account metadata. `progress.json` has counts, fixed error
codes and per-resource completeness/access status. The link phase uses a
separate `links-<snapshot-id>` folder with encrypted versions and its own
aggregate progress file. STOP or the GUI Stop button requests graceful shutdown.
The GUI announces completion/failure; per-contact failures remain in the local
audit. The key is discarded on shutdown; resuming requires entering it again.

To tune a running updated link collector, atomically write `speed.json` in its
`links-<snapshot-id>` directory, containing only `{"requests_per_second":3}`.
This changes the requested ceiling without a restart/key entry. The collector
keeps a separate adaptive ceiling; down/up changes cannot undo throttling.
Mandatory Retry-After/backoff deadlines survive live speed changes. Malformed,
non-finite, boolean or out-of-range settings keep the last valid speed. Speed
is not part of strict archive identity, so completed rows remain resumable.

Status-file writes and reads have bounded retries for temporary Windows locks.
Link databases include a `diagnostics` table with the operation stage, exception
class and numeric OS codes; exception messages/URLs/keys are excluded. Successful
link transactions remain authoritative even if the following status write fails.

`reclassify_terminal_markers.py --output-directory <private folder>` repairs
only old `invalid_json` completion labels when a saved exact legacy HTML end
marker is proven, encrypted provenance matches, and accepted pages/counts/IDs
form a continuous prefix. Original responses remain unchanged and each repair
is audited. Foreign-model or unrelated HTML responses cannot end a resource.

Snapshot APIs and link requests are distinct: raw list links stay untrusted.
The old snapshots and preflight remain available for later historical-version
seeding. Unknown old email/bot keys cannot be manufactured from contact IDs.

Frappe's existing data and staff permissions are not overwritten by collection.
After collection, compare actual available fields and source IDs before scoped
imports. Roles/permission matrices, lesson-builder content and other gaps remain
explicitly unproven; Data Export API requires separate schema/access discovery.

## Immediate delivery without another AVO key prompt

`stream_archive_to_frappe.py --job-directory <existing private snapshot folder>`
follows the already running MVC reader. It needs the existing verified SSH
identity, not the AVO key. `--once` sends one bounded links/page cycle for initial
verification. The destination is fixed to the MVC backend and MVC site; the
sender batches up to 100 links and 20 raw pages per cycle, with a 4 MiB page
batch target (one larger source page remains intact). This avoids one server
startup per tiny page while keeping only a small working buffer in memory. The
private payload travels only on SSH stdin. The standalone receiver uses the
existing site encryption key and `private/avo-ingest/archive.sqlite`, outside
the downloadable files directory. No Docker image/layer or HTTP route is added.

Server commit and independent decrypt/read-back precede each exact receipt.
After acknowledgment, one local transaction stores that receipt and replaces
only the link ciphertext with an explicit `REMOTE:MVC-FRAPPE:v1:` reference.
Version IDs, token digests, contact cursors and learning records remain intact.
Freed SQLite pages are reused; no VACUUM, full local copy or drive D is used.
Raw resource pages are streamed too, retaining their current fixed local copy
while the parent reader is open. `delivery/progress.json` logs aggregate counts
and fixed errors, never source values. `delivery/STOP` stops only the sender;
ten consecutive transfer failures or less than 128 MiB free also put a STOP
marker in the parent job so collection cannot fill the disk unchecked.

This is encrypted source retention on the Frappe server, not an activation of
legacy login links or an overwrite of current user profiles. Future readers
must fetch remote references from the encrypted archive rather than feed them
to Windows DPAPI. Retain the MVC site's existing encryption key in its protected
server backups and explicitly include `private/avo-ingest`: default private-file
backups may cover only `private/files`.

## Verification

Run `python -B -m unittest discover -s experiments/learner-staff-sessions
-p 'test_*.py'` from the repository root. Fixtures are synthetic and perform no
network calls. Coverage includes source/UID mismatch, archive/source immutability,
DPAPI round-trip and tampering, key redaction, truncated HTTP retries,
provider-wide retry delays, duplicate pages/IDs, false end markers, partial
403/404 responses, resume, writer locking, STOP, ten-error limits and final
link-phase error propagation.

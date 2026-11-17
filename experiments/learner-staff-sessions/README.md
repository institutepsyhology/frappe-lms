# MV-Centr API archive and learner-link preservation

The collection utilities are read-only toward AVO. The separate, explicitly
started MV/IOMP contact applier below creates local Frappe records from completed
source captures. Collection alone does not apply contacts, change credentials or
redeem personal links. Actual learner/staff session isolation remains separate.

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

## Parallel Master Vision server job

MVC remains the default immutable process profile, preserving existing formats,
archive paths and Windows DPAPI encryption. The separate Master Vision worker
selects `AVO_ARCHIVE_ACCOUNT=mastervision` before imports, fixes the source to
`https://shop.mastervision.su` and the destination to `my-lk.mastervision.su`, and
uses distinct archive schemas and encryption binding. Unknown accounts and mixed
source/target metadata fail closed. A running process cannot switch profiles.

`install_mastervision_archive.py --release <published Git SHA>` installs only
reviewed source bytes into a versioned private directory on the existing MV
site volume. It does not add Docker layers or recreate services. The program
manifest is checked again at startup. `launch_mastervision_archive.py --release
<SHA>` opens one masked local field for the MV GET key; the key travels through
SSH stdin and then a pipe to a detached server worker. There are no secret CLI
arguments/environment variables/files. It remains only in process memory.

The worker stores the encrypted raw API pages and individual-card links directly
under `my-lk.mastervision.su/private/avo-api-archive/job-20261116`, using the site's
existing encryption key. No contact data is saved on the laptop. Collection
starts at one request/second, has its own locks/STOP/progress, and resumes existing
source checkpoints. The server job survives a laptop/SSH disconnect; a worker or
container restart requires the owner to enter the API key again. Site encryption
key backups must cover this directory as well. Raw list personal links remain
untrusted for authentication. This source archive does not itself create all
LMS accounts or implement learner/staff session isolation.

## MV/IOMP contact application and owner priority

`apply_server_contacts.py` has only the fixed `mastervision` and `iomp` targets;
it cannot target MVC. Install the exact published private bundle with
`install_server_contacts.py --release <SHA> --account <mastervision|iomp>`.
Run the installed program as the existing site owner from the bench sites
directory with `--account <account> --apply --limit 20` for a pilot. After an
independent read-back, `--account <account> --start` starts its detached writer.
The native application containers and in-memory-key AVO readers stay running.

The contacts resource must be complete, not the entire 26-resource capture.
`server_contact_reader.py` proves metadata, encrypted envelopes, raw hashes,
terminal marker, continuous pages, exact counts and ID fingerprints against both
saved indexes. It reads with short closed cursors; ongoing source commits are
not pinned by a long SQLite transaction. Full validation precedes any write.
The invalid list-returned learner links are dropped rather than imported.

New native Users retain their source password plus the verified encrypted
support copy, have welcome mail disabled and remain Website Users. Existing
identities/passwords/roles are preserved. Marketing flags are positive-only.
Social-only/no-email sources become Contacts. Shared-email and missing-password
sources also become separate Contacts with the original email and AVO identity;
they are not deferred or merged. Native email rows require the durable Contact
identity mixin. Source rows and passwords do not enter logs. A Contact is not a
fabricated native User login; its source credentials remain in the encrypted
archive for the separate learner-authentication phase.

Each site's `private/apply-avo-contacts` contains `state.sqlite`, safe aggregate
`progress.json` and its immutable release. `STOP` pauses that site's writer.
The default RQ queue must have fewer than 100 pending jobs; a queue-overload race
retries the same record after rollback. Ten consecutive genuine failures stop
the writer. Less than 2 GiB free on the server pauses application writes.

Owner priority: finish MV contacts, then MV contact/course/lesson access. IOMP
continues in parallel and must not delay MV access. IOMP course/lesson migration
must precede its access synchronization. The old local access database has only
MVC namespace data; do not substitute it for MV. Contact completion is not proof
of completed grants or of working authentication from imported personal links.

The Contact guard is installed through `extend_doctype_class`. It binds only an
exact account/source ID and protects against foreign native queued User contact
updates, which otherwise select a Contact by email. A small published source
overlay can be installed with `deploy_contact_binding.py --release <SHA>
--baseline <previous SHA>` while AVO keys remain in the backend's process memory.
It verifies source hashes in six app containers, keeps server-only rollback
copies, patches the live source atomically, and persists the identical read-only
file mounts in the canonical Compose file. It builds no Docker image/layer and
does not recreate the backend. Refresh web/RQ processes and clear hook caches
before resuming contact application. On a later full image deployment, explicitly
update or remove these versioned file mounts once the image includes the same
guard; do not leave an old hooks overlay hiding a newer image's hooks.

The live Gunicorn command uses `--preload`: an HUP alone is not activation
evidence. Call the Administrator-only, metadata-only
`lms.lms.avo_contact_binding.binding_status` through actual HTTP/MCP and require
`active: true` from the serving worker before replaying shared-email Contacts.
A fresh standalone Python process is not proof of the HTTP worker's controller.

After changing this policy, pause only the affected contact application workers,
retain all source collectors, install the new private applier release, and start
with `--start --retry-issues` to retry earlier deferred identities. Never remove
another operator's STOP marker or the MVC owner-request stop.

## Verification commands

Run `python -B -m unittest discover -s experiments/learner-staff-sessions
-p 'test_*.py'` from the repository root. Fixtures are synthetic and perform no
network calls. Coverage includes source/UID mismatch, archive/source immutability,
DPAPI round-trip and tampering, key redaction, truncated HTTP retries,
provider-wide retry delays, duplicate pages/IDs, false end markers, partial
403/404 responses, resume, writer locking, STOP, ten-error limits and final
link-phase error propagation.

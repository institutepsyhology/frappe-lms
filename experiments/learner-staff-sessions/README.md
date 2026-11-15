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
  and `--refresh` (append fresh versions). Default at most one request/second.
- `legacy_api_snapshot.py --output-directory <private folder> --collect-links`:
  GUI collection of the 26 documented legacy resources available to the key,
  followed by individually verified learner links. One masked GET key remains
  in the process's memory for both phases; there is no secret command argument
  or environment variable. The GUI shows the current resource and link progress.

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

## Verification

Run `python -B -m unittest discover -s experiments/learner-staff-sessions
-p 'test_*.py'` from the repository root. Fixtures are synthetic and perform no
network calls. Coverage includes source/UID mismatch, archive/source immutability,
DPAPI round-trip and tampering, key redaction, truncated HTTP retries,
provider-wide retry delays, duplicate pages/IDs, false end markers, partial
403/404 responses, resume, writer locking, STOP, ten-error limits and final
link-phase error propagation.

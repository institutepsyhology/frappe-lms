# MVC direct archive delivery, 16 November 2026

The owner requested immediate server delivery because laptop storage cannot be
expanded. The sender follows committed records from the current source job,
without restarting its reader, obtaining its AVO key or changing learner records.
It streams bounded memory-only batches over the existing host-key-verified SSH
channel to the fixed MVC site. The receiver is a standalone reviewed program,
so no application image, Docker layer, public endpoint or session change is needed.

126 synthetic tests ran successfully (one Linux filesystem-permissions test is
skipped on Windows). Coverage includes exact ACK before eviction, lost ACK and
idempotent retry, whole-batch rollback, remote ciphertext binding/tampering,
source/account isolation, concurrent source commits, existing collector resume
after explicit remote references, full page/link round-trip, ten transfer failures
and low-disk stops. An existing Windows control-file timestamp collision was
reproduced and fixed by rereading the bounded speed control; a regression test
forces a same-size replacement with the same timestamp.

The live preflight confirmed the MVC backend running, an existing MVC site key,
and about 8 GiB of server free space. No existing learner login was redeemed.

Initial live delivery committed and independently verified 100 personal-link
versions before local ciphertext eviction. The first raw API page was correctly
left local when rejected: the legacy paginator begins at zero. Receiver checks
now accept an exact integer page >=0 and still reject negative/boolean pages;
the page/link pipeline fixture also uses the real zero-based page convention.
The original raw ciphertext was never deleted. Safe receiver error codes are
propagated to the delivery status without private payloads.

The corrected receiver/sender were published before use. Independent live
read-back found 500 links and three raw pages, successfully decrypted the first
and last record of each kind, and reported SQLite quick_check=ok. File permissions
were 0600 and directory permissions 0700. An unauthenticated request to the
archive's direct URL returned HTTP 404, without exposing a database.

The sender was started separately in the background; the original AVO reader
was not restarted and its key was not accessed/re-entered. A later 20-second
observation showed 500 further confirmed links with no delivery/source failures.
Raw page delivery was then bounded to 20 records and a 4 MiB target per cycle,
avoiding one remote startup per tiny page; 12 sender regression tests passed,
including continuation across 22 source pages. Only the sender was restarted
gracefully, preserving its delivery cursor and all source captures.

At the final observation, server-confirmed receipts covered 9,600 personal-link
versions and 342 raw pages. The source had collected 24,120 links; its concurrent
advance explains the small difference from the sender's earlier queue snapshot.
Both jobs were active with zero current failures. The pending queue had fallen
from about 22,500 to 14,500 links, so delivery was faster than new collection.
Sender memory was about 28 MiB. Private source data and record hashes were not
published. This is live encrypted retention, not completed import of all contacts
or proof of legacy-link authentication.

The encrypted archive is under the site's private/avo-ingest directory. Protect
the existing site key and include this path explicitly in server backups; a
normal private/files backup alone is not evidence that the archive is backed up.
This retention does not yet implement the separate learner/staff login feature.

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
Actual server delivery and background operation must be checked after publication.

The encrypted archive is under the site's private/avo-ingest directory. Protect
the existing site key and include this path explicitly in server backups; a
normal private/files backup alone is not evidence that the archive is backed up.
This retention does not yet implement the separate learner/staff login feature.

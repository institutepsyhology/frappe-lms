# Retry a saturated Frappe background queue

The selected-recipient batch importer previously classified Frappe's
`QueueOverloaded` (a subclass of `ValidationError`) as a bad contact. The
server now distinguishes it as transient; the client reconciles the whole
batch and retries missing records with backoff, stopping after ten consecutive
unsuccessful attempts. The queue itself is not cleared or modified.

Once the selected-recipient worker had stopped at a verified checkpoint,
`requeue_batch_conflicts.py` marked 10,288 unresolved selected IDs from the
affected window for another attempt. Contacts verified in the meantime and
records outside the selected MV-Centr list are excluded. Real validation
errors remain subject to the ordinary ten-consecutive-issues stop. The worker
was restarted in batch mode; its first reprocessed contacts were verified
independently against the source ID and email.

On 2026-11-12 the guarded release activated image
`sha256:687cb6952613928285195f8726b8934a98c51b2b7385a1997987e4e8ddd7e63c`
from source `41b4ef8e2c09ed9df38876880314c4f3aafeeae7`. The previous image
was `sha256:3f6d1884e2dee5dff756a44376214080f89f2e545f24cb8ec1efd878e01d402b`.
Backup gzip checks, image startup, three-site health and nondecreasing-count
checks passed. Both background workers resumed; the course 11 and lesson 26
source-ID resolver continued to work. Backup integrity is not a restore test.

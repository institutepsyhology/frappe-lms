# Selected MV speed verification

## Cause and final change

Before this change the default queue had 98 jobs, of which 97 were native
`frappe.core.doctype.user.user.create_contact` mirrors. One short/default worker
handled them; the importer waited at its 100-job queue gate. Source-ID searches
already used indexes. The measured import pace was roughly 1.5 identities/second.

Final private worker release: `9f521c18898d635f7a40e77bd40690346360654a`.
Only the selected MV writer opts into native Contact creation in the User creation
transaction. No mirror is omitted. Other enqueue calls, including background
threads, retain their native behaviour. Unsupported callbacks fail closed; the
original enqueue and native mapping-compatible job context are restored finally.
An existing email-matched Contact is rejected before mutation, and exactly one
mirror bound to the new User/email is required before commit. Name collisions use
a deterministic account/source-ID Contact name with the same native validation.

Native password hashing, current-hash verification, encrypted support copy,
source-ID/profile read-back, source bans and marketing opt-outs are preserved.
There is no hash-strength reduction, new permission, welcome mail, or source write.
The selected writer has no artificial sleep after successful records; queue and
disk reserve checks remain. On restart, captured positive opt-outs are loaded once
for completed-record replay; new creations retain live pre/post-insert checks.

The selected individual collector's existing speed control is now 5 requests/sec
instead of 3. Its adaptive ceiling/backoff and ten-consecutive-failure stop remain.
The collector was not restarted and retained its GET key in memory. No key is
persisted and no general MV/IOMP STOP was removed. No Docker image rebuild,
additional image layer, HTTP-worker restart or cross-account migration occurred.

## Validation and live recovery

104 targeted synthetic tests passed, including transaction rollback after native
mirror/password failures, foreign-user/foreign-thread delegation, mapping-compatible
native context, name-collision fallback, selected scope and positive opt-out replay.

The first pilot rejected the normal Redis PubSub cache listener under an overly
strict total-thread-count guard, before committing those records. This was replaced
with main-thread ownership and explicit delegation of other threads. Two isolated
native name collisions also exposed a non-mapping job context; both conditions were
fixed and those records successfully replayed. Neither issue remains deferred.

Five ordinary inline imports passed source-field, real login hash, decrypted
support-copy, native Contact, enabled/ban and no-welcome-email checks. Both recovered
collision cases have exactly one correct mirror and a support copy matching their
login hash. Source data, addresses, passwords, personal URLs and source IDs are not
included in this report.

An intermediate sustained window measured 603 new Users in 167.3 seconds:
3.61/sec, approximately 13,000/hour, versus roughly 5,000/hour before. The same
window captured 798 links: 4.77/sec, approximately 17,200/hour. The main queue fell
from about 100 pending jobs to zero during that window. This was measured before
the final removal of the writer's 50 ms delay.

At the final recovery check the destination had 70,520 MV Users and 5 source-only
Contacts; the collector had 44,948 verified individual links. The selected writer
and collector were alive, application issues were empty, and the collector had zero
failures since its latest restart. Both general MV/IOMP jobs remained paused.

These are live-window measurements, not a guaranteed completion deadline. The
269,196-identity selection is unchanged and both jobs continue in the background.

## Final steady-window measurement

After the final delay removal and recovery, a 332.5-second window added 1,396
native Users: 4.20/sec or approximately 15,116/hour, about three times the original
pace. It captured 1,597 more links: 4.80/sec or approximately 17,293/hour, about
1.6 times the original 3/sec collector setting. At the final check the destination
had 71,916 source-bound Users plus 5 standalone source Contacts, and 46,545 links.
The queue was empty, the selected writer was alive, application issues were empty,
and individual collection had no failures since its latest restart. General jobs
were still paused. These results and the exact source releases were published and
the local checkout synchronized without changing unrelated work in progress.

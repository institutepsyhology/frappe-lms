# Selected MV speed improvement

Measured baseline: about 1.4 imported identities/second. The default queue stays
near its 100-job import gate; 97 of 98 pending jobs are native User.create_contact
mirrors. One worker serves short/default while long is idle. Source-ID lookups
already use indexes; adding another index would not address this bottleneck.

Replace only the selected, single-threaded MV import's known create_contact enqueue
with the same native function inside the User creation transaction. Preserve User
lifecycle hooks, native Contact identity validation, current-hash verification,
encrypted support-password storage, read-back, per-ID commit/recovery, opt-outs,
queue/disk gates, selection and prior general STOP markers. Verify the native
Contact mirrors the exact new User before commit; unexpected callback changes fail
closed. Other queued jobs retain their semantics. Default general import behaviour
and app HTTP workers are untouched. No shared app monkeypatch or container restart.

This avoids one RQ enqueue/fork/boot/commit cycle per new identity without dropping
the native Contact. A second queue worker was considered but the two CPU server
already has load above two and would still perform the redundant scheduling work.
Skipping mirror creation entirely was rejected to preserve framework behaviour.
Password hashing/verification costs are not reduced.

Increase the existing private individual collector speed control from 3 to 5
requests/second. Its independent adaptive ceiling, provider backoff and ten-error
stop remain intact; do not restart it or discard the in-memory GET key.

Publish and install the private release, stop only the selected applier between
records, resume its existing ledger, validate real User/Contact/password samples,
measure sustained post-change import/link deltas and queue depth. Keep production
source data and status ledgers private. Record measured results, not a promised
multiplier. If native read-back fails, roll back that record and revert the private
writer release; source collection remains independent.

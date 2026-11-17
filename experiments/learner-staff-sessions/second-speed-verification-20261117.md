# Second selected-MV optimization: verification

## Identity contract

Migration membership and access matching remain keyed by AVO account + contact ID.
Email is not a replacement identity and duplicate addresses are not merged. The
optimized email lookup belongs to Frappe's internal User-to-Contact mirror creation.
Its nonunique index changes no account data, uniqueness rule, permission or URL.

## Native lookup index

Published index release: `56cb5fb5e35c69feee697935355d3ba232bb03dc`.
The hash-verified patch was applied only to the MV database, MariaDB 11.8.9/InnoDB.
The new covering index is (email_id,parenttype,parent), Non_unique=1. The registered
application patch is idempotent. Live NOCOPY/LOCK=NONE DDL completed in 1.19 seconds;
the session metadata-lock wait was bounded at five seconds and restored afterwards.

EXPLAIN changed from ALL/~109,152 rows to ref/1 row with Using index. Median native
lookup timing fell from 27.06ms to 0.092ms, about 294x for this query. This does not
imply the same multiplier for the full import. A 446-second initial post-index window
created 1,299 Users (2.91/sec), versus approximately 2.52/sec in the preceding window.
Native workload and other server activity vary; no sustained 294x import claim is made.

## Private durable journals

Published tuning release: `c875511416a7d32703b8b90d97c8052a5968e6db`.
Server SQLite is 3.46.1. The selected application/state.sqlite and encrypted
individual/profiles.sqlite both changed DELETE to WAL with FULL=2. The tuner checked
account/site/scope metadata and reported each file configured. The existing writers
already explicitly use FULL; live mode changes did not alter that connection setting.
Tuner FULL read-back is not presented as direct introspection of another process.
Synthetic tests with old writers and readonly readers proved continued commits,
visibility and rollback; continuous-writer/held-transaction tests verified normal
SQLITE_BUSY handling. Eight targeted migration/journal tests passed.

Both old worker PIDs remained alive, no GET key was re-entered, and no process,
container, image, source account or general migration job was restarted. Private
WAL files were approximately 4MB each, with automatic checkpointing continuing.
The verified-link database already used WAL/FULL and was untouched.

The first 222-second post-WAL window measured 2.43 Users/sec and 4.58 links/sec;
there is no evidence here for a large extra whole-job gain from this setting.
Measured CPU usage was about 98% on two cores with 0.5% I/O wait. MariaDB already
had a 384MiB buffer pool and durable log flushing; those parameters were not changed.
The remaining limit is largely CPU/native record work under the current load.
Password hashing and verification were not weakened, skipped or batched.

## Final read-back

The final check found 115,795 source-bound Users and 7 standalone Contacts in MV,
with 118,675 verified individual API links/cards. Five newly created records passed
exact account/ID, native mirror and recoverable-password/current-hash checks. Native
read-back began after the independently committed ledger-ID snapshot to avoid a
stale MariaDB repeatable-read view. Application issues were empty; the collector had
zero failures since its latest restart. The default queue was empty. Both private
journals read back as WAL and general MV/IOMP STOP markers remained present.

Scripts, source hashes and this sanitized report are published; no CSV content,
contact identity, password, source key or personal URL is in Git. The same 269,196-ID
selection continues in the background. These checks establish current progress and
sampled persistence, not completion of the entire import or legacy-link login support.

Online-index semantics were checked against [MariaDB documentation](https://mariadb.com/docs/server/reference/sql-statements/data-definition/create/create-index).
Journal persistence and FULL behaviour were checked against [SQLite WAL](https://sqlite.org/wal.html)
and [PRAGMA documentation](https://www.sqlite.org/pragma.html).

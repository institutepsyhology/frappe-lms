# Selected MV private journal tuning

The native email-lookup index changed ALL/~109k rows to covering ref/1 row, with
27ms median reduced to 0.092ms. Aggregate creation initially rose from roughly
2.52 to 2.91/sec. Remaining warm native work was measured at 0.208-0.26sec per
record with a forced transaction rollback; this does not weaken hash verification.
The application ledger and encrypted individual-profile database still use SQLite
DELETE journaling with synchronous=FULL. The verified-link database already uses
WAL/FULL. Concurrent durable journal writes add disk overhead.

Switch only application/state.sqlite and individual/profiles.sqlite under the
exact selected MV scope to persistent WAL. Keep FULL and per-record commits;
do not use NORMAL/OFF, delayed acknowledgements or batched account transactions.
Validate site/account/scope metadata before changing anything. Bound busy waits;
if a database is in use, leave its mode unchanged and report it. No forced locks,
process termination, table rewrite, checkpoint truncation or API-key access.

Synthetic tests prove an existing writer and existing readonly connection can
continue through an external WAL switch, with old writer FULL still 2, rollback
unchanged, and committed rows visible. Independent continuous-writer and held
transaction tests confirmed normal SQLITE_BUSY handling and successful retry
after releasing the transaction. All source tables and API payloads stay intact.

Apply a hash-verified published helper on the same local site volume already used
by the link WAL. Record live SQLite version and before/after modes, check both
existing PIDs/counters continue, compare sustained native-User/link deltas, retain
general MV/IOMP pauses and publish sanitized measurements. New jobs are not started.

# Second selected-MV speed improvement

The source identity remains AVO account + contact ID. This change does not match,
merge, rename, or grant access by email. It accelerates the framework's native
lookup of its linked Contact, which is called by both the guard and native helper.

Live evidence: `get_contact_name` filters Contact Email by email_id and parenttype,
then reads parent. The child table has only name/parent indexes. EXPLAIN estimates
an ALL scan of 104,751 rows for every lookup. The selected writer is healthy and
its queue is empty; source-ID lookups already use their indexes. Ledger GROUP BY
costs about 39ms per progress update, roughly 2ms per inserted identity, so it is
not the first optimization to change.

Add one nonunique covering index (email_id,parenttype,parent), using MariaDB
NOCOPY/LOCK=NONE and a five-second metadata-lock wait. Reject an unsupported online
operation rather than silently copying/locking the table. Preserve existing index
constraints, reject a conflicting same-name index, and verify exact columns and
nonuniqueness after DDL. Register an idempotent application migration for future
deployments; apply only to the MV database now from a hash-verified public source.

No source collector, importer, app container or API-key process is restarted.
No account data, import scope, ID routing, password policy, flags or access changes.
Do not raise the existing 5/sec API limit for this experiment. Other accounts stay
paused. Snapshot aggregate import/link counters before and after, compare the
lookup plan/timing and sustained native-User creation rate, and read back real
native mirrors/support passwords. Publish the patch, reproducible application
script and sanitized verification; keep private data and source keys out of Git.

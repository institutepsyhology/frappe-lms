# Implementation and verification

1. Audit archive boundaries and target model. The source contains separate access
   records, independent lesson flags, historical observations and missing general
   course endings. Native enrollment alone loses this information and may open
   too much. A source ledger is therefore required before runtime activation.
2. Stream a minimal, validated gzip payload with a private manifest and stable
   per-record/aggregate fingerprints. Keep the source SQLite read-only and apply
   account/contact/course exclusions before transmission.
3. Create a read-only custom Frappe registry through a reproducible trusted bench
   operator. No application image rebuild is needed for this data/schema phase.
   Resolve mappings in bounded batches, insert atomically, and verify source and
   mapping fields. The normal LMS models remain the only runtime access engine.
4. Validate synthetic source/target/worker cases and a small live batch. Run one
   resumable server worker with persistent state and safe journals. Replays use
   the registry's immutable source identity, rather than an unverified cursor.
5. Compare final count and aggregate hash, read representative records through
   MCP and publish source, tests and verified results to the established branch.
6. Restore recorded lesson allowance with a conservative snapshot boundary.
   The owner confirmed numeric maximum access ID as the current relationship;
   keep earlier entries as history, including when the newest is restrictive.
   Preserve unsupported rules in the registry and expose specific pending reasons.

Alternatives considered: plain Enrollment is insufficient for lesson selection,
dates and freezes; native Grant alone cannot represent missing Users/Contact-only
profiles and lacks source provenance; a new runtime authorization engine would
duplicate existing LMS logic. The registry plus native grants avoids both data
loss and a second authorization system.

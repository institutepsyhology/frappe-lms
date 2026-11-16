# MV and IOMP contact application, 17 November 2026

Owner priority is MV contacts, then MV course/lesson access; IOMP contacts run
independently in the background. IOMP course content must precede IOMP grants.
The MVC no-new-contacts stop and installed insertion guard are unchanged.

Before application, native Codex MCP independently returned zero source-tagged
Users on both destinations. Source contacts resources were complete: 563,218 MV
and 124,212 IOMP records. The MV course-access resource also completed with
172,696 source rows. These are archive counts, not applied grants or users.
The earlier local access SQLite contains only MVC namespace records and cannot
serve as an MV/IOMP archive. No cross-account source substitution is permitted.

The source reader passed 17 synthetic tests, including a second SQLite writer
committing while the reader generator is paused. The new applier passed 12
transaction/account/queue/disk tests; contact mapping passed 11 tests and the
MVC no-new-contact regression suite passed 11 tests. The existing bundled Python
runtime supplied cryptography; no packages were installed on the laptop.

Published application release: 52c65df2d64b5569349f03af3064f0ea1aead1fc.
Both destination-private installations verified all four source hashes and the
startup manifest. No Frappe application code/image, container, collector process,
AVO key or source setting was changed or restarted.

Each site created an initial 20 real native Users. Independent source-to-target
read-back verified all 20 profiles/source bindings, all 20 current-password
hashes, all 20 decrypted support copies, Website User status and disabled welcome
email. Native MCP independently confirmed 20 source-tagged Users on each site.
These pilot checks are not evidence that all contacts have already migrated.

After both pilots passed, separate detached application workers were started.
They have per-site ledgers, locks, STOP controls and safe progress counters;
MV has a shorter pacing delay. Both validate the complete contacts resource
before writes, without waiting for invoices/other API resources or personal links.
Pending queue capacity and a 2 GiB disk reserve delay the current record rather
than discard it. Existing source workers remain independently active.

Deferred shared-email or invalid source rows stay in the account-specific ledger.
They are not silently merged, granted another person's courses or assigned fake
emails. Existing identity lookup prevents duplicate creation after a restart.
An unusual exception from an after-commit callback requires independent database
reconciliation: a later rollback cannot undo an already committed account.

Account creation does not activate old personal-login URLs or synchronize access
grants. Those stages remain explicitly separate and retain the owner's priority.

The first live background check observed 131 created MV Users and 112 created
IOMP Users (pilots included), with no failed ledger decisions. Both application
workers were alive and waiting normally for the shared default queue to drain
below the conservative threshold. Both original AVO collectors remained alive
without a source error. Server free space was 7.13 GiB; MVC retained its explicit
owner-request STOP. These are dated observations, not final migration totals.

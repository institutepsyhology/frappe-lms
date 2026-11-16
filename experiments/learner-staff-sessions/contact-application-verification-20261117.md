# MVC application and IOMP collection, 17 November 2026

The owner requested continuation from the completed MVC source archive and,
independently, confirmed that the additional ISP source is shop.iomp.ru.
The live MVC coverage audit verified all 213,885 source rows and their aggregate
ID fingerprint against the completed server archive. Existing identities cover
123,295 eligible source records, with 15 owner exclusions and one protected
identity. Missing identities are 90,552 unique-email users, seven contacts without
valid email and 15 shared-email cases. Rules remain in private operator policy.

The writer preserves existing profiles/passwords/roles and applies only positive
marketing restrictions. New Users use the deployed Administrator import method
and its verified encrypted support copy; no welcome email or course enrollment
is requested. No-email/social-only contacts keep their source identity. Shared
email contacts are deferred because native Contact validation links by email;
they require a durable identity guard rather than an insert-only workaround.

192 synthetic tests passed, with one Unix permissions check skipped on Windows.
Coverage includes source completeness/privacy, mapping, positive-only opt-outs,
read-back/rollback, new source bans, literal passwords, worker/account isolation,
IOMP key transport and existing MV/MVC regressions. Both operational paths use
private standalone programs; the running MV process and application containers
do not need restarting. Existing unrelated source edits remain untouched.

The first 20 new MVC Users passed independent field, current-password and
encrypted-support-copy checks; welcome mail remained disabled and all were
Website Users. Native MCP confirmed all 20 source identities. The background
writer then created 1,291 users before being paused at a record boundary to
handle native QueueOverloaded responses. All 678 rejected attempts rolled back;
they are replayed from the same source with --retry-issues after queue controls.

Native User.on_update queues create_contact after commit, and the framework
checks queue capacity before registering that callback. The writer now waits
when the default queue has 100 pending jobs and retains the current source row.
Race-condition QueueOverloaded failures roll back and retry the same row with
bounded waits; the tenth unsuccessful retry stops without moving to another ID.
These transient conditions no longer classify valid source people as errors.

The owner also supplied the IOMP GET key in the masked window. The dedicated
IOMP worker was confirmed collecting on its own site, with 23,498 contacts saved
and no source error at observation. MV continued with its completed 563,218-contact
traversal and was reading course-access records. No application container or
existing source collector was restarted. These observations do not prove that
all contacts are already applied or that legacy authentication is activated.

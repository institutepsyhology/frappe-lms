# MVC application and IOMP collection, 17 November 2026

## Owner correction: existing MVC cohort only

The owner explicitly prohibited further new MVC accounts: the people with
courses had already been migrated. The earlier interpretation of continuation
as permission to add all remaining source contacts was incorrect. The writer
is stopped with an owner-request STOP marker, and its process has exited.
The final ledger has 1,292 created Users (including the pilot), not 1,291.
Independent read-only queries found no login, enrollment, access grant or
System User in this newly created cohort. Nothing has been deleted.
The 678 rejected inserts rolled back; they must not be replayed as creations.
The source now also rejects insertion before beginning a database transaction
and skips identities outside the existing target cohort, even without STOP.
No CLI option enables account creation.

The read-only credential audit excludes all 1,292 ledger-created source IDs.
The old cohort contains 123,298 distinct source identities: 112,920 Users and
10,378 Contact-only identities. Every old User has a login-password hash;
112,918 also have an encrypted support copy. The two exceptions are covered
by existing owner exclusion/protection instructions and were not changed.

All 19,226 old Users with course enrollments have a source password and a
separately captured, individually verified personal link. 19,225 have a support
copy; the remaining protected account is left unchanged as instructed.
Thirty evenly spread enrolled Users passed decryption and current-hash checks.
This sample does not establish full current-hash verification for 112,918 copies.

The vault audit decrypted and verified all 213,885 individual link records:
site/account/snapshot/version/metadata binding, payload hash, original host/path,
matching UID and token hash, plus the complete source-ID fingerprint. Links
cover 123,297 old identities. One target-only User without courses has no record
in the latest capture. An older archive has its password and an invalid
list-repeated link, so that link must not be attached to the person. The target
already has a login hash and encrypted support copy. Details remain private.

Links are retained in the encrypted source vault, keyed by source identity.
They are not yet exposed in contact cards or redeemable by Frappe authentication.
Do not report data coverage as functional passwordless login. Contact-only
records likewise do not have native Frappe login credentials.

## Earlier observations (superseded scope)

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
writer was observed at 1,291 users before being paused at a record boundary to
handle native QueueOverloaded responses. All 678 rejected attempts rolled back;
the later final ledger has 1,292. These attempts must not be replayed as new
accounts after the owner's scope correction.

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

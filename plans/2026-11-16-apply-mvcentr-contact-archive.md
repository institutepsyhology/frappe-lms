# Existing MVC credentials and source archive

Updated owner scope, 17 November: do not create new MVC contacts or Users.
The people with courses were already migrated. Work only on their existing
source identities; preserve current passwords, enrollments, progress, roles,
profile edits and positive marketing restrictions. Do not merge by phone/email.

The broad creation job is stopped; its final ledger records 1,292 newly created
Users. No automatic deletion is authorized. They have no enrollments, grants or
login activity at the read-only check. Retain the private ledger for an explicit
future decision. Never replay the 678 rolled-back attempts as account creations.
The fixed existing-only source guard also blocks insertion if STOP is removed.

The old cohort contains 112,920 Users and 10,378 Contact-only identities.
All Users have password hashes; 112,918 have encrypted support copies. Existing
excluded/protected exceptions remain unchanged. Thirty enrolled-user samples
passed support decryption and comparison with current login hashes; this is
sample evidence, not proof of every copy's present usability.

All 19,226 people with enrollments have an archived source password and a
verified individual personal link. Decrypt/validate the whole link vault against
site/account/source identity, envelope/payload hashes and full ID fingerprint.
Do not use the repeated personal-link fields from contacts list responses.
One old target-only identity without courses needs a new individual source
capture; its old list-derived link is invalid and cannot be substituted.

Data retention and working authentication are separate. The verified links
remain encrypted on the MVC server; card actions and local link redemption are
still pending the same-host learner/staff session work specified in
`specs/2026-11-15-learner-staff-sessions.md`. Do not relabel original AVO URLs as
working Frappe links, reset passwords, create dummy logins or duplicate contacts.

MV and IOMP source collectors continue independently in their own site-private
directories. This MVC policy does not stop or mix their captures. Do not restart
application containers while their API keys exist only in worker memory.

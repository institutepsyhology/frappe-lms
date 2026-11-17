# Preserve contacts with shared email, 17 November 2026

Owner instruction: transfer contacts as they are by AVO ID; do not defer shared
email records. The mapper now creates separate native Contacts for shared-email
or missing-password sources, retaining native email rows, original source email,
source account/ID, names, phones, social fields and positive marketing flags.
It never fabricates a login address/password or assigns another person's User.
Source passwords/personal links remain in the encrypted source archive; a Contact
is not a new native User login. Existing MVC creation remains stopped.

Published source and installed contact-applier release:
555e664bae82dae7761ace738f807195dd4ddd6b.
The Contact extension resolves a User only by the exact source account and ID.
It also blocks foreign native queued create_contact profile updates before
persistence. Ordinary unmapped Contacts retain their native behaviour.

66 targeted tests passed: 23 binding/authorization checks, five card/resolver
checks, 14 transaction/resume checks, 13 mapping checks, and 11 MVC creation-stop
regressions. Two unrelated historical schema tests have stale expectations and
were not changed; no broad suite pass is claimed.

All three source files were independently hash-verified in six application
containers. The canonical Compose file retains the same three read-only source
mounts per app service and a server-only prior-config rollback copy. No image
was built, the existing image remains at 51 layers, and the backend container
was not restarted/recreated. The two queue containers and scheduler were
refreshed separately; source collectors retained their original PIDs and keys.

Gunicorn uses --preload. Activation was proven through real native MCP calls to
the Administrator-only binding_status endpoint on both destinations: active was
true in the serving HTTP worker, not merely in a new command-line process.

The three previously deferred MV records were replayed and committed as three
separate Contacts. Independent source-to-target checks confirmed every profile,
native email and source ID, absent foreign User links, and unchanged collided
User profiles/authentication values using private before/after fingerprints.
Real Contact.save checks in rolled-back transactions preserved identity; foreign
native job contexts were rejected before the test name change could persist.
The identity of existing Users, their passwords and course references was not
reassigned or merged.

Both appliers resumed with --retry-issues from their existing ledgers. A later
live check confirmed MV: 16,987 Users plus three Contacts; IOMP: 13,084 Users plus
62 Contacts, with zero deferred and failed decisions. Both application workers
and the original AVO collectors were alive. These are observations during the
ongoing migration, not final counts or completed course-access synchronization.

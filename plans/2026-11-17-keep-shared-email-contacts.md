# Preserve shared-email contacts by AVO identity

The owner explicitly instructed importing contacts as they are, keyed by AVO ID,
rather than deferring a record because its email is shared. Keep MV/IOMP source
workers active and MVC creation disabled. Do not merge people by email/phone,
invent addresses/passwords, replace current User passwords or alter existing
enrollments. Source account plus canonical source ID is the person identity.

Frappe's native User requires a unique email identity. Preserve a shared-email
source as a separate Contact with native email child rows, original source email,
name, phone, social fields, marketing restriction and AVO ID. A valid-email source
without a password is likewise a Contact, rather than silently skipped. Source
passwords and personal links remain in their encrypted source archives; creating
a Contact does not invent a native login or grant another User's courses.

A durable Contact controller mixin must suppress email-based automatic User
binding for mapped source contacts, resolving only an exact account+source ID.
Reject incomplete/foreign/ambiguous bindings. Ordinary unmapped contacts keep
native behaviour. Also check native queued User.create_contact context: that
job selects a Contact by email and changes names/phones even without assigning
user, so a foreign source identity must fail before persistence.

The applier must verify this mixin is active before inserting source Contacts
with native email rows. Preserve and verify each Contact email and source ID.
Replay the existing deferred records through the updated native lifecycle,
then resume both background appliers from their ledgers. No in-memory-key source
collector or backend container may be restarted.

Use a published, file-hash-verified source overlay on all existing app containers
and persist the same read-only file mounts in the canonical Compose file.
This avoids adding Docker image layers or recreating the backend while source
keys are in RAM. Refresh web workers and background worker processes separately
as needed; preserve sites/log volumes and the old Compose/source rollback files.
Compare the prior hooks source against the published baseline before patching.

Verify synthetic cross-identity cases, duplicate-email Contact insertion and
later edits, native queued foreign-profile updates, rollback and idempotent
resume. Then check the real recovered Contact by source ID, original profile,
native email, absent foreign User link and unmodified collided User. Ensure both
AVO collectors and both contact appliers continue, with no remaining deferred
shared-email cases. Publish source, deployment steps and safe evidence to GitHub.

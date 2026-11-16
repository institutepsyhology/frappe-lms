# Apply completed MVC contact capture to existing Frappe identities

The owner requested continuation after source retention completed. Current MVC
Frappe has 123,298 distinct source identities; the completed archive has 213,885.
Apply the missing identities and positive marketing restrictions, preserving
existing profile edits, source bindings, roles, enrollments and current passwords.
Use exact account+source ID, never merge people by phone or email. Load exclusion
and protected-ID rules from a private policy file; do not publish real IDs.

Consume only the completed encrypted MVC server archive. Verify all envelopes,
raw pages, ID coverage and the source fingerprint in a full read-only pass before
applying. Raw list login links are invalid and must be excluded; keep verified
personal links in their separate encrypted archive for the authentication phase.

Create missing unique-email Users through the existing Administrator importer,
including its verified support-password copy and welcome-email suppression.
Preserve legitimate no-email/social-only identities as Contacts. Existing
passwords are never replaced; fill a missing support copy only if the archived
password matches the current login and the target is not protected staff. Apply
only positive opt-outs, never clear current ones. Existing profile fields remain
unchanged because an empty value could be an intentional operator edit.

The installed Contact controller auto-links by email; an imported duplicate-email
Contact could therefore point at another source ID. Do not use that unsafe path.
Log those cases separately while the other records proceed, then implement a
scoped identity guard without stopping the in-memory-key MV source job. Capture
individual issues by source ID/fixed reason only; ten consecutive genuine failures
stop the writer. Persistent checkpoints and identity read-back reconcile commits
after restart, avoiding duplicate accounts. Publish source before server use.

Start with a full audit, then a small real batch and independent MCP read-back.
After checks pass, continue in a server-side background worker. No contact payload
is downloaded to the laptop. The additional ISP source job needs its exact origin
confirmed first; the MVC application can progress independently meanwhile.

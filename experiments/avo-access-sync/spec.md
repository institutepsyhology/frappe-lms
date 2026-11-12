# MVC archived access migration

Restore contact/course/lesson relationships from the verified historical MVC
archive without mixing AVO accounts, inventing identities, publishing courses,
or losing personal dates, freeze states and independent lesson flags.

The source is the latest successful access projection in the MVC namespace and
its verified collected range. The separately supplied foreign example is outside
that range. The archive is an October snapshot, not evidence of current account
completeness. Respect private contact exclusions and the course exclusions of the
existing content migration.

Acceptance criteria:

- One immutable source ledger document per source access ID, including repeated
  contact/course pairs. Preserve hashes, capture times, unknown values, dates and
  the complete independent lesson flags; omit names, email and credentials.
- Match target identities strictly by AVO account and source ID. Missing contacts,
  Contact-only profiles and missing courses remain explicit pending relationships.
- A rerun cannot duplicate or overwrite a source snapshot. Pending mappings can
  refresh after contacts/courses arrive. Read back every saved payload before
  confirming it and verify the final count and aggregate fingerprint.
- Store progress and safe error codes persistently; stop on uncertain writes or
  conflicting source evidence. No full archive copy or memory-heavy database load.
- Runtime activation uses the existing LMS access model only after source rules
  are understood. The owner explicitly selected unlimited general course terms;
  personal end dates and freezes remain independent. No guessed opening dates.
- Check tests, a small production batch, MCP read-back and GitHub publication.

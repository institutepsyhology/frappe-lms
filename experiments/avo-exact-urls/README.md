# Original AVO URLs on the LMS domain

The lesson preview remains at `/personal/training/<course-id>/view/<lesson-id>`.
The editor remains at `/shop/training/traininglessons/admin/update?id=<lesson-id>&lg=ru`.
The course link `/personal/training/<course-id>` selects the existing enrollment
resume pointer or the first accessible mapped lesson. Source IDs are resolved
only within the account belonging to the current site. Duplicate IDs, unavailable
lessons, invalid query IDs and denied edit permission fail closed.

Website route rules serve the SPA at these exact root paths without an HTTP
redirect to an invented URL. Root browser history keeps ordinary LMS pages under
the configured LMS prefix. Login return addresses retain path, query and hash.
Previous internal lesson URLs remain supported; the old edit form continues to
validate both course and lesson IDs. Native course administration keeps its LMS
route. Mapped course cards link directly to the original AVO course path.

The source context comes only from the committed revision. The existing deployed
lesson source has unrelated differences from the repository; a hash-checked
minimal delta preserves those differences. The guarded release reuses fresh
three-site backups, health/count checks and rollback support. DNS and domains
are not part of this change.

Released 2026-11-12 from source 687f3c3c661d0ced8ffd954def6bb8f7de59db29
as image sha256:4191f318740c845d0dbdeb8c7de574d62fc62be582cca6ac20004449628b51ea,
replacing 7ea71aa30403ba41266cb7fc3787b964dba949b69130dd9073afad4a89fdb8d2.
Eighteen backend and 138 frontend tests passed, followed by the production build.
Fresh database backups passed gzip integrity checks. Three-site health and
nondecreasing record-count checks passed; the password worker resumed.

Authenticated browser checks confirmed literal preview and editor addresses,
loaded editor blocks, course-only entry selecting lesson 809 of course 206,
old internal preview compatibility and ordinary sidebar navigation. The excluded
837/7642 example remained unavailable. Actual browser form login from both root
URLs returned to the exact requested address, retaining query and fragment.
Live MCP resolved MV-Centr lesson 809 and course 206; the same editor lookup
returned null on IOMP and Master Vision. Existing course content was not edited
or published during verification. Source-ID save behavior and learner resume
fallback were covered by tests; no live learner account was changed.

A guest app-menu PermissionError also occurs on the ordinary native guest course
page; it is recorded separately in BACKLOG.md and did not prevent the verified
login return. Backup integrity checks are not a restore test.
The unpublished catalogue also exposed /personal/training/206 as its actual copyable course href.

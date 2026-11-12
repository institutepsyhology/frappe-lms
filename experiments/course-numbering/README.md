# Stable numeric IDs for new courses and lessons

MVC course and lesson URL IDs now continue in separate site-local sequences.
The custom_lms_id field is immutable, unique per DocType and is not copied when
cloning a record. Imported AVO records keep their exact source IDs in both the
public field and unchanged provenance; new native records have no invented AVO
provenance. Existing document names, course references and enrollment keys stay
stable. The same original AVO URL paths support both imported and native IDs.

An InnoDB Series row serializes each sequence until transaction commit. Deleting
a record does not reduce the high-water mark or reuse its ID. Failed, rolled-back
insertions may reuse uncommitted IDs. Numbers identify records, not lesson order.
The import adapter sets a genuine source identity before creating its lesson
skeleton, so imports do not consume native IDs and later change their identity.

The MVC floor comes from the complete saved catalogue (972 courses, max1016)
and accepted lesson manifests (7579 unique lesson IDs, max10242), including
excluded and test records. It is deliberately higher than the target lesson max
10230. Two existing native courses and six native lessons are numbered first.
Future imports that collide fail closed; parallel future AVO creation after the
snapshot needs source-bound reconciliation before import.

MV and IOMP native numbering remains inactive until complete source catalogues
can provide their reservation boundaries. Their schemas are installed and any
imported identities are copied, while their unnumbered native records stay NULL.
The migration is preflighted, supports dry_run and is safe to repeat. The release
changes backend code only; it reuses the verified frontend bundle.

On 2026-11-12 image
sha256:d4a1f221ed802b0625963909334c067d0ba6f164563193519416537e8d9b2d8d
was activated from source cb5f3455c78752b233b338d4a7c2c7f73928e289
(after the initial 86819d75 numbering migration). The installed Frappe Series
column was verified as signed INT(11), InnoDB; allocation is capped at its
2147483647 limit. All 55 backend tests passed. Fresh gzip-checked database
backups, three-site health and nondecreasing-count checks passed. Password
backfill resumed after each guarded activation.

All 971 MVC courses and 7569 lessons have unique protected numeric URL IDs;
969/7563 imported source identities remain unchanged. Existing native records
consume IDs1017-1018 and10243-10248, so the next new IDs are1019 and10249.
The migration rerun changed zero records. The user confirmed that native
numbering for Master Vision and IOMP should wait until their databases migrate.

The live smoke script created draft native course/lesson fixtures, resolved,
read, saved and read them back by ID, deleted and replaced a lesson without
reusing its ID, and rolled all fixture data and production counter changes back.
Four independent DB connections then issued eight unique consecutive numbers
through an isolated UUID Series row; its high-water mark was verified from a
fresh transaction and the temporary row removed. Production counters and the
imported206/809 route round trip remained unchanged. A live MCP lookup also
resolved existing native lesson10243 to native course1017 with empty provenance.
Backup integrity checks are not a restore test.

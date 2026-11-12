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

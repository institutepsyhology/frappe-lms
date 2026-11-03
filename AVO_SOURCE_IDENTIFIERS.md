# AVO source identifiers

The LMS keeps its native document names and adds the original numeric source ID
and source account to both courses and lessons. The mapping key is
`(doctype, custom_avo_account, custom_avo_id)`; the same ID from another AVO
account must never be treated as a match. A migration must check for duplicate
keys before creating or linking a record and preserve source ordering.

`avo_mapping_fields.execute` is an idempotent Frappe bench entry point for the
four custom fields. It contains no personal data, source content, private
videos, access tokens, or learner access records. Course contents, original
images and authenticated migration logs must remain in the authorized site or
private local storage, not in this repository.

New courses are created unpublished. A source identifier is a reference for
later access migration; its presence does not grant anyone access. Verify
course and lesson mapping, chapter order, original media pairs, and actual
player behavior before treating a migrated lesson as complete.

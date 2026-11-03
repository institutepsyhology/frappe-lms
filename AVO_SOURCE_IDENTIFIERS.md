# AVO source identifiers

The LMS keeps its native document names and adds the original numeric source ID
and source account to both courses and lessons. The mapping key is
`(doctype, custom_avo_account, custom_avo_id)`; the same ID from another AVO
account must never be treated as a match. A migration must check for duplicate
keys before creating or linking a record and preserve source ordering.

`lms.lms.avo_mapping_fields.execute` is an idempotent Frappe bench entry point for the
four custom fields. It contains no personal data, source content, private
videos, access tokens, or learner access records. Course contents, original
images and authenticated migration logs must remain in the authorized site or
private local storage, not in this repository.

New courses are created unpublished. A source identifier is a reference for
later access migration; its presence does not grant anyone access. Verify
course and lesson mapping, chapter order, original media pairs, and actual
player behavior before treating a migrated lesson as complete.

## Verification 2026-11-03

On the intended isolated site, the four custom fields were created through the
authenticated application API and read back through DocType metadata. Four
unpublished courses and eleven draft lessons were read back: their source IDs,
course references and chapter ordering match the pilot source data. Course
images are stored on the site. The video pairs and material links were checked
against the locally retained source data; player playback has not been verified
in an authenticated browser session. One lesson has a known incomplete source
video, which remains recorded in the private migration backlog. No learner
access records were created.

The field installation code is recorded here for reproducibility; the running
site's custom fields were created through the application API, not by deploying
this file into the current image. Invoke the entry point only after the code is
installed into the intended Frappe app version.

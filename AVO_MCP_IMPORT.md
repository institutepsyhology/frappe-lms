# AVO lesson import through the native Frappe MCP

The existing MCP `call_method` tool invokes `lms.lms.avo_import.import_lesson`.
It requires System Manager, accepts exactly one lesson per call, and defaults
to `dry_run=true`. A call with `dry_run=false` creates only an unpublished
course and a draft lesson; it never creates enrollments or publishes content.
An existing matching draft course with one chapter can receive a new lesson.

The input `payload` contains `account`, `source_origin`, decimal `course_id`
and `lesson_id`, independently verified `course_title` and `lesson_title`, and
one of these representations:

* `format: "preview"`, with ordered `content` blocks (`text`, `links`, `audio`,
  `video_pair`, and `image`); or
* `format: "ape"`, with the decoded source `ape` page tree. Source capture and
  association with the course remain the calling operator's responsibility.

For `preview` an image block has `type: "image"`, a caller-selected `image_key`
and optional `caption`. The separate `images` argument maps each image key to
base64 PNG, JPEG or WEBP bytes, not a path or URL. Each image is limited to 5 MB,
4096 by 4096 pixels, with at most ten images. They are attached as private lesson
files. An image or screenshot is inserted as an image; OCR or link discovery
from screenshots is not performed by this method. Course cover image upload is
available separately through the existing `frappe.client.attach_file` method.

`source_origin` and `account` must match the target site; existing AVO mapping
fields must already be present. Both are caller-supplied provenance and are not
proof of where the submitted bytes were obtained. The method preserves original
video URL strings, `{name}` and other text variables. The current video player
may normalize playback URLs; warnings identify parameters it may discard.

Dry-run reports unsupported structures and performs no write. Any unknown block,
unsupported HTML, ambiguous identity, incompatible video pair or changed existing
lesson stops creation rather than silently dropping it. A successful import saves
the submitted snapshot as a private lesson attachment. Its result always says
`source_complete: false`: source captures and APE styling, release rules,
homework, player behavior and rendered content require separate verification.
An identical retry verifies the saved snapshot, images and lesson before returning
`already_imported`; changed content is never overwritten. The method serializes
imports per site until the database transaction commits or rolls back.

This source file and tests contain synthetic data only. Never commit actual
lesson contents, students, screenshot bytes, authentication information, or
private media links to GitHub.

The reusable schema definition is `lms/lms/avo_mapping_fields.py`; the current
backend-only image does not include it. The four fields can also be created via
the authenticated native MCP `Custom Field` document API, deliberately and
independently on each intended site. The importer does not install them itself.

# AVO MCP import verification — 2026-11-05

Two source lessons were imported through the existing mv-centr MCP endpoint into an existing unpublished course. Dry runs reported readiness before writes. MCP read-back confirmed both source account and source IDs, draft status, association with the existing course, lesson ordering, and private source attachments. The course remains unpublished.

The importer reported `source_complete: false`, `ape_layout_settings_not_rendered`, and `ape_video_settings_not_reconstructed`. This check does not establish visual equivalence, playback, learner access, schedules, or homework behavior. No source content, personal data, authentication, or private URLs are included here. The deployed importer code was not changed as part of this verification.

Subsequently six more unpublished courses and twelve draft lessons were imported through the same endpoint after source identity checks and dry runs. MCP read-back confirmed source IDs, accounts, course membership and draft state; course ordering was checked for the two multi-lesson courses, and private source attachments were checked for four individual lessons. The same reconstruction limitations apply. One historical course was unavailable at its editor URL and was recorded for separate review.

Two further unpublished courses and six draft lessons were subsequently imported after the same source and dry-run checks. MCP read-back confirmed their IDs, draft status and six private source attachments; the five-lesson course ordering was checked. Unsupported media and HTML cases were withheld for review. No lesson contents or private URLs are included in this report.

One further unpublished course and three draft lessons were imported; their IDs, course association, order, draft state and private source attachments were read back through MCP. The guarded batch then stopped on repeated unsupported styled links; the source snapshots are retained locally for review.

After deploying the styled-link fix, an additional unpublished course and draft lesson were imported and their account, source IDs, course association and private source attachment were read back. Formatting reconstruction is explicitly warned as incomplete. Another course still requires review for unsupported HTML containers; it was not imported.

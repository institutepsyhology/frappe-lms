# AVO MCP import verification — 2026-11-05

Two source lessons were imported through the existing mv-centr MCP endpoint into an existing unpublished course. Dry runs reported readiness before writes. MCP read-back confirmed both source account and source IDs, draft status, association with the existing course, lesson ordering, and private source attachments. The course remains unpublished.

The importer reported `source_complete: false`, `ape_layout_settings_not_rendered`, and `ape_video_settings_not_reconstructed`. This check does not establish visual equivalence, playback, learner access, schedules, or homework behavior. No source content, personal data, authentication, or private URLs are included here. The deployed importer code was not changed as part of this verification.

Subsequently six more unpublished courses and twelve draft lessons were imported through the same endpoint after source identity checks and dry runs. MCP read-back confirmed source IDs, accounts, course membership and draft state; course ordering was checked for the two multi-lesson courses, and private source attachments were checked for four individual lessons. The same reconstruction limitations apply. One historical course was unavailable at its editor URL and was recorded for separate review.

# Safe import of AVO video-wrapper links

The converter accepts `div.video_wrapper` containing inline content, converts it to a paragraph, retains link labels and destinations, strips presentation attributes and flags formatting loss. Unknown wrappers, nested block content, duplicate attributes, active attributes and unsafe URLs remain rejected. The source snapshot is retained privately. A link's original target and visual styling are not reproduced.

The guarded release verifies the exact installed image and its base-image layer prefix and importer-only overlay, builds a replacement overlay, tests the candidate, checks database backups and service health on the three sites, and rolls back on failure. Publish and deploy one exact reviewed commit. Record the image, health and actual MCP verification after deployment. Source content, authentication and private URLs must not be published.

## Release verification, 2026-11-05

Published source `879c6b4108cce108d169cb67ad591976d02610ea` produced image `sha256:506218e9301b4dc824f66dcd3ff05ba5438d43199e3236204235b08bfb851199`. Candidate tests and database-backup integrity checks passed; all application services and three sites passed health checks, and site counts, languages and access-release switches were unchanged. Actual mv-centr MCP dry-runs accepted three previously rejected lessons with explicit formatting-loss warnings. One request failed immediately after restart and succeeded on retry. Backups were not restore-tested. Display, playback and learner access remain unverified.

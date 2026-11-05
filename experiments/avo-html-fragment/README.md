# AVO static HTML fragments in Frappe lessons

The converter can preserve a narrowly validated static HTML fragment byte for byte in the existing sandboxed `htmlBlock` EditorJS tool. It rejects scripts, forms, frames, event handlers, unknown classes, unsafe URLs, unsupported CSS and malformed structure. Rendering, link navigation and visual equivalence require independent checks; source snapshots remain private. The source limit remains bounded, now accounting for observed larger lessons; explicit legacy video pairs with an unused default second-provider field retain both URLs. Existing safeguards and stop-on-unknown behavior remain in place.

The release verifies the running image and exact base-layer ancestry, builds a replacement backend overlay, runs candidate tests, verifies backups and health across the three sites and rolls back on failure. Publish one reviewed commit before deployment and record the resulting image and real MCP tests afterwards. Never commit actual lesson HTML, media links, users or credentials.

## Release verification, 2026-11-05

Source commit `9397a92bc17d5718ce38df75a8426972859e331c` produced image `sha256:3f17259b3d8233c36db2d4abf812289b61c76cc5a139b96b10c6c24cf234ccae`. Candidate tests and database-backup integrity checks passed; services and all three sites passed health checks, and site counts, languages and access-release switches were unchanged. An actual mv-centr MCP dry-run accepted a validated multi-link static HTML fragment and returned `ape_static_html_frame_unverified`. This was a dry-run only: no lesson was created, and frame rendering and link navigation remain unverified. Backups were not restore-tested.

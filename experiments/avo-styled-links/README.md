# Safe import of AVO links with presentation styles

The converter preserves the link destination and text, strips only its `style` attribute, and emits the existing formatting-loss warning. Other unsupported attributes, duplicate attributes and unsafe URLs remain rejected. Original snapshots remain private attachments. This change does not reconstruct the original visual style.

The guarded release starts from the exact previously installed image, builds an overlay containing the importer modules, tests the candidate, verifies backups and service health on the three sites, and rolls back on failure. Publish the reviewed source first and run the release from that exact commit. Verify actual MCP behavior and record the image digest and result after deployment. No real source, media or authentication data belong in this repository.

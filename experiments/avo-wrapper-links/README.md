# Safe import of AVO video-wrapper links

The converter accepts `div.video_wrapper` containing inline content, converts it to a paragraph, retains link labels and destinations, strips presentation attributes and flags formatting loss. Unknown wrappers, nested block content, duplicate attributes, active attributes and unsafe URLs remain rejected. The source snapshot is retained privately. A link's original target and visual styling are not reproduced.

The guarded release verifies the exact installed image and its base-image layer prefix and importer-only overlay, builds a replacement overlay, tests the candidate, checks database backups and service health on the three sites, and rolls back on failure. Publish and deploy one exact reviewed commit. Record the image, health and actual MCP verification after deployment. Source content, authentication and private URLs must not be published.

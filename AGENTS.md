# Server changes and GitHub

- User instruction, 2026-10-24: every server change must be saved to this GitHub repository as part of the same task. Ordinary publication of the corresponding source changes is already authorized.
- Keep deployed code reproducible: save source, translation catalogs, safe configuration templates, build instructions, and verification results. Verify the published revision matches the deployed release.
- Never commit credentials, tokens, private keys, real environment files, database backups, or personal data.
- The current production baseline is LMS 2.64.0 (`7c46bb8f4976222b3f6aa84368551c424edaa194`) with Frappe 16.53.0. Verify the actual deployed release before subsequent changes. Do not upgrade unrelated upstream code while changing localization.
- Run relevant regression tests and a production build before deployment. Preserve the previous image and a documented rollback path. Do not force push or rewrite unrelated history.

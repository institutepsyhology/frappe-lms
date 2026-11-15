# Contacts, employee positions and individual course access

This release separates contact editing, employee delegation and credentials.
Users and contacts share one card. Course rosters use bounded server pages and
one person/course dialog, with immutable issuance metadata for new grants.
Permanent and timed denies take precedence over every additive grant.

Positions are explicit per-site assignments. No existing employee is silently
assigned a new position. Native technical roles cannot be delegated. Legacy
Moderator contact/course operations remain available, but direct role changes
are Administrator-only; bounded delegation uses the new Employees screen.

The AVO role reference was read with explicit account-owner permission. Its
82 groups and 280 unchecked options are reference material, not imported staff
authority. Captures remain private and are excluded from this repository.
The current matrix exposes implemented contact, course-access, employee,
position and credential actions; native LMS author roles remain separate.

## Verified before production activation

- 120 Python tests and 67 frontend tests in the isolated image build.
- Normal production frontend build succeeds with source maps disabled in the
  actual frappe-ui plugin configuration; no additional host RAM is required.
- Real MariaDB/controller preflight on `access-stage2.local`: social-only
  contacts with blank name/email, placeholder phones, unified SQL directory,
  explicit read-only contact permission and legacy-path denial.
- Real roster with 205 synthetic students: all page sizes, global sorting in
  both directions, phone fallback, end dates, hidden-contact privacy, opaque
  enrollment tokens, all-grant course denies, timed lesson denies, reopening,
  removal preserving user/progress and immutable AVO source payloads.
- Real staff controllers: subtree delegation, actor/parent ceilings, native
  API/document escalation denial, self/ancestor protection, deactivation
  preserving records and transaction lock release. All 16 checks passed.

The preflight found and corrected two installed-framework incompatibilities:
missing-name Contact saves require the narrowly validated document flag, and
new deterministic access blocks require explicit insert rather than save.

## Release procedure

Commit/push the source revision, run `create_context.py OUTPUT` outside this
checkout, upload its context and committed release helpers privately. Build
against the pinned 50-layer base; the candidate must have exactly 51 layers
and match every manifest source hash. Run the three smoke scripts only on the
isolated stage, then `release.py prepare` and `release.py activate IMAGE
BACKUP_MANIFEST REVISION` on the LMS host. Setup performs only targeted,
additive DocType reloads. Fresh three-site backups and existing encryption
keys are verified before activation; service/count/ping failures restore the
previous image. Additive schema remains backward-compatible on image rollback.

Production data, sessions, keys, database backups and private deployment
configuration are never included in the context or Git repository.

## Explicit limits

- Contact-only records have no fabricated login; their archived access is
  read-only until a real User/social-login association exists.
- A historical source that did not record its issuer/time remains labelled
  unknown; capture/import metadata is shown separately.
- Browser interaction with the user's open AVO tab is unavailable in this
  session. The role reference used authorized, read-only source requests.
  Component and server checks do not claim a human browser visual review.

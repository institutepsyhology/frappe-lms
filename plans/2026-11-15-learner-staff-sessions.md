# Same-host learner and staff authentication migration

Status: archive audit and individual-card preflight utility complete;
live preflight needs a newly entered API GET key. Authentication implementation
and production migration remain pending.
Contract: `specs/2026-11-15-learner-staff-sessions.md`.

## Settled owner decisions

- One common hostname, currently my-lk; later shop.
- Separate `/personal` and `/shop` portals with independent passwords/sessions.
- Imported personal links allow repeated login until explicit revocation;
  blocked accounts may not redeem them.
- Existing person/course/lesson IDs and source-account separation remain intact.

## Why routing changes alone are insufficient

Native Frappe reads a root `sid` and even permits a form/query SID override.
It constructs the native request/session and checks CSRF before `before_request`
and `auth_hooks`. A late hook or a second login URL cannot independently select
two sessions. The existing LMS StudentView is presentation-only, and native
impersonation replaces the session and writes login metadata.

The session boundary therefore belongs before native session/CSRF handling.
Namespace browser requests, cookies, CSRF, authenticated APIs, private media,
websocket handshakes and frontend caches. The external client must not choose a
trusted realm through an arbitrary header, Referer, native `sid` override or
unscoped API credential.

## Phases and completion evidence

1. **Preserve/verify AVO credentials, without activating authentication.**
   Verify actual archived URL variants and coverage using a read-only scan.
   Keep exact raw values private; report aggregates only. Compare API origin,
   contact ID, `auth_links.user` and documented raw field. Preserve multiple
   captured versions; reject ambiguous cross-contact/cross-account mappings.
   Inspect current import persistence; do not claim that local capture means
   the Frappe login route is already functional.
   **Confirmed source defect:** all 2,139 raw list pages repeat the last row's
   personal link. The archive has 211,735 wrong row-to-UID associations. Do not
   backfill Frappe from these rows or construct a new link by replacing UID.
   The new preflight reads three individual cards, checks both response ID and
   link UID, and saves only the documented link field in a separate private DB.
   Bulk repair is not enabled until that live preflight succeeds.
2. **Prove identity/session isolation on the staging site.**
   Keep all existing learner references and system-admin rights. Resolve the
   native User email/identity constraints explicitly; do not create dummy email
   identities. Prototype early trusted request selection and independent
   authentication principals linked to the same person. Demonstrate independent
   login, logout, recovery, staff deactivation and media/websocket access before
   applying changes to production identities.
3. **Implement locally redeemable personal links.**
   Import only `link_personal_auth`; encrypt recoverable original URLs and index
   a keyed account/site-bound digest. Store provenance, revocation and usage
   separately from contact fields. Old imports must not reset revocation.
   Redeem through the learner authentication boundary, recheck current account
   status, record real learner security events and redirect to a clean path.
   Never delegate validation back to AVO after cutover.
4. **Implement actual learner preview.**
   Add explicit member-specific read/gate helpers shared with real learner
   access. Keep authenticated staff as actor. Return denial codes/dates without
   protected contents. Provide a preview read-endpoint allowlist and explicit
   mutation guards; disable automatic progress/watch/visit events in the UI.
   Bind temporary previews to actor/session, account, target and course scope.
5. **Expose authorized contact actions.**
   Distinct position capabilities for learner-link Copy/Open/Revoke and
   temporary-preview creation. Existing password-read rights do not imply them.
   Render separate labelled actions and a permanent preview banner; staff
   workspace does not expose personal student enrollments.
6. **Verify and release.**
   Unit/permission tests plus real HTTP tests with independent cookie jars;
   same-browser tab tests for the core concurrent-session requirement. Compare
   DB snapshots for forbidden preview writes. Check legacy/encoded URL samples,
   wrong-account tokens, revocation, login history and denied native APIs.
   Back up database/keys, preserve the previous image, publish exact tested
   sources/templates, migrate additively, verify all sites and rollback paths.
   DNS/subdomain replacement is a later explicit cutover, not this release.

## Challenge and alternatives

- **One native User, two login forms:** cheapest, but a shared SID and staff
  privileges violate independent-session and learner-authority requirements.
- **Native impersonation / frontend StudentView:** already available but changes
  sessions or retains instructor bypasses and can write learner progress.
- **Separate hostnames:** simplest native cookie isolation; declined by owner.
- **Same host with early realm isolation:** selected requirement; must prove the
  full request boundary in stage before accepting any production auth change.

Avoid unrelated upstream upgrades, duplicate contacts, moved enrollment IDs,
new storage services and unnecessary media/content processing. A production
schema or credential switch must not be presented as complete from unit tests
or MCP persistence alone.

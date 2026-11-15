# Separate learner and staff sessions, preserving AVO personal links

Status: audited requirements; authentication migration is not deployed.

**Legacy archive blocker found:** every saved list-response page repeats the
personal link of its last contact. Only 2,139 of 213,874 row-to-link associations
match the row's contact ID. The other 211,735 associations must not be imported
as credentials. Fetch individual cards and verify UID/key ownership first.
See `experiments/learner-staff-sessions/verification-20261115.md`.

## Problem and required behaviour

One person may be both a learner and a staff member. The current LMS uses one
native Frappe login, password and root session cookie. Its `studentView` option
only hides staff controls; it does not impersonate a particular learner or
prevent learner-progress writes. It cannot satisfy the requested behaviour.

Keep one shared public hostname: `my-lk.mv-centr.ru` now, `shop.mv-centr.ru`
after the owner performs the final domain cutover. Learners use `/personal`;
staff use `/shop`. Separate hosts were considered and declined by the owner.
Preserve existing AVO course and lesson URL formats and numeric IDs.

## Approved requirements

- Separate learner and staff credentials, login pages, sessions, logout and
  password recovery. Both sessions must work concurrently in the same browser.
- Link both identities to the same person without duplicating contacts,
  changing AVO IDs, inventing email addresses or migrating enrollment/progress
  references to a new person.
- Staff workspace shows only work allowed by the staff position and course
  scope. Personal learner enrollments do not grant staff authority or appear
  as staff work. Deactivating employment must not disable learner access.
- Password support actions refer to learner credentials. Staff credentials are
  separate; password visibility does not automatically permit either login-link
  operation.

### Real learner login link

The official contacts API field is `link_personal_auth`. The local exporter
already retains it verbatim in `auth_links.user` and in the raw API response.
Verbatim preservation alone does not prove the link belongs to that row: the
source list endpoint itself returns mismatched link associations. This is a
confirmed blocker for importing that archive field, not an encoding problem.
Import this documented field only; do not infer a staff link from other fields.

The owner selected repeated login until explicit revocation. Blocking/disabling
the learner must always prevent redemption. Importing an older archive must
never undo a local revocation. Any future password-change/revocation policy
must be explicit and must not silently change this selected link policy.

Preserve the original path, query encoding and opaque key. Domain migration
changes only the permitted origin. An imported AVO link must be resolved
locally after cutover, without depending on the original AVO service.

An imported key grants only learner authentication, never staff authority.
Successful real login records date/time, trusted client IP, OS/browser and login
method in learner security history. Normal learner actions update that person's
progress, homework and forms. This must leave the current staff session intact.

### Staff preview link

Separate position permission; temporary, bound to an authenticated staff actor,
target learner, site/account and allowed course scope. It is not transferable
client authentication. Display a persistent staff-preview warning and provide
separate Copy/Open buttons with an explicit warning not to send it to clients.

Reads must use the learner's actual assignments, restrictions, dates, freezes,
lesson prerequisites, progress and homework. No instructor bypass applies.
Locked lessons explain their denial without returning protected lesson content.

Preview never creates a learner session/login-history entry and never changes
progress, watches, last-opened lesson, homework, submissions, notes, enrollment,
purchases or certificates. Record actor/target events in a separate staff audit.
The browser UI and direct forged API requests must obey the same restriction.

## Legacy-link verification boundary

Official AVO documentation calls the link temporary, but supplies no signing,
expiry or rotation contract. Treat captured keys as opaque imported credentials.
Do not invent an AVO signature verifier or authenticate from a contact ID alone.

Only captured versions can be recognized locally. A link formerly sent in an
email/bot may contain an earlier key that is absent from all available archives.
Such a key must go to a clean sign-in/recovery page. Unknown keys must never be
silently accepted. Before cutover, compare read-only API samples with archived
versions, retain separately captured valid versions and report unmatched cases.

Store reusable URL material encrypted, index a site/account-bound keyed digest,
and audit only non-secret event identifiers. Do not publish contact data, URLs,
tokens or encryption keys in Git, application analytics, request/access logs or
error reports. The login landing response must remove secret query parameters
before loading the LMS, set no-store/no-referrer, and avoid third-party assets.

## Acceptance checks

1. Two tabs on the same hostname retain independent staff/learner identities
   across login, refresh, password recovery and logout. Learner requests cannot
   use staff credentials or native APIs to acquire staff authority.
2. Imported old paths and encoded queries resolve the right account/person on
   both current and future permitted origins. Wrong-account, edited UID/key,
   unknown, revoked and blocked-account cases fail closed.
3. Real link login updates learner security history and progress normally;
   email-scanner GETs do not create logins or learner activity.
4. Staff preview produces identical allow/deny results to real learner access
   without changing learner data, including under forged direct requests,
   media loads, video events, quiz/assignment/SCORM submissions and navigation.
5. Permission/position changes take effect on the next preview request. Expired,
   wrong-session, wrong-account and out-of-scope previews are denied.
6. Existing Users, Contacts, AVO mappings, grants, progress, homework and current
   system-administrator rights are preserved throughout migration and rollback.
7. Source changes, configuration templates, checks and deployment evidence are
   published to the authorized GitHub repository without private data.

## Non-goals

Partner authentication, changing course content, bulk password resets,
changing the public DNS before final cutover, or updating unrelated upstream
Frappe/LMS versions.

## Evidence

- Official AVO API: https://autoweboffice.com/help/ru/api/api-akkaunta-na-platforme-avtovebofis
- Existing collector: `contacts-api/export_contacts_api.py`, `selected_record`.
- Frappe v16.53 request lifecycle: https://github.com/frappe/frappe/blob/v16.53.0/frappe/app.py
- Native authentication: https://github.com/frappe/frappe/blob/v16.53.0/frappe/auth.py
- Existing presentation mode: `frontend/src/composables/useStudentView.ts`.

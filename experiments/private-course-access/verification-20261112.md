# MVC private course release — 12 November 2026

The selected behavior is that a learner sees only their assigned courses.
Imported courses remain private, existing assignments work, and new accounts
receive no automatic course membership or lesson permission.

## Deployed source

- Baseline image: `sha256:d4a1f221ed802b0625963909334c067d0ba6f164563193519416537e8d9b2d8d`.
- Frontend source revision: `9dfb89886286c8a9a801a53897ccfec7f137aec3`.
- Installed image: `sha256:5bbab8f6c6ddbbb63dcd71dcfb53600e6e518420c6e6ff266e1c1c62d800cebb`.
- Probe corrections: `67de7e24` and `fd99572e`; these are separately invoked
  trusted verification operators, not application image changes.
- Sources are published on `feature/avo-mcp-import-20261103` in the existing
  `institutepsyhology/frappe-lms` repository.

The first candidate stopped before activation because the baseline directive
did not export the already-used `titleText`. The successful context includes
the committed compatible directive and its two existing HTML regression suites.
Package dependencies were unchanged and checked against the pinned baseline.

## Final MVC state

| Check | Result |
| --- | ---: |
| Imported courses, unpublished and self-enrollment disabled | 969 |
| Granted imported lessons enabled, audience All, preview off | 7,519 |
| Other imported lessons retained as drafts | 44 |
| Native imported grants, unchanged | 97,958 |
| Native imported enrollments, unchanged | 97,958 |
| Grant lesson assignment rows, unchanged | 1,280,993 |
| Remaining course settings or lesson staging changes in read-only plan | 0 |

A three-lesson pilot also applied the self-enrollment setting to all imported
courses. The follow-up enabled the remaining 7,516 lessons. Every document was
saved through its controller with acknowledged private before/after journaling,
content/source identity readback and per-document commit. Grant lesson sets,
personal terms, freezes, opening rules and enrollment identity signatures were
identical before and after. The public grant-expanding publish-All action was
not used. No historical pending/frozen/expired record was activated by this task.

Independent connected MCP counts confirmed the final course, lesson, draft,
grant and enrollment totals. A repeated read-only operator plan reported zero
remaining changes and the original assignment signatures.

## Verification

- 73 frontend tests across six suites passed in the candidate image; the Vite
  build completed. The old membership/default-tab source had reproduced four
  failures in the earlier focused checks, and the corrected source passed.
- 14 synthetic data-operator tests, 12 release/context tests and 6 persisted
  session/transport tests passed.
- Actual HTTPS probes passed for an ordinary assigned learner, an ordinary
  unassigned account and Guest. They checked course details, the enrolled list,
  original AVO course/lesson routes, lesson JSON, and rejection of raw Lesson
  REST reads and instructor-only fields.
- The original migration example passed after release. A separate restricted
  membership check opened one allowed lesson while denying another released
  lesson in the same course through both source and positional endpoints.
- An authenticated request with a valid CSRF token was rejected by the actual
  self-enrollment policy. Typed filter checks used the native JSON POST contract.
- Temporary audited probe sessions were removed. Existing session counts,
  login metadata, enrollment progress/current lesson and lesson/video tracking
  state were unchanged by the probes.
- All nine overlaid source files matched the source manifest. Twelve HTTPS
  asset hash comparisons across the three sites matched the installed image,
  including the course list and actual course-detail component chunks.
- All six application services run the same installed image; three-site pings
  and nondecreasing data counts passed. Image layers increased from 45 to 47;
  no service reported an out-of-memory termination.

Fresh, verified private database/config backups for all three sites were
prepared before the pilot and activation. The guarded image activation only
cleared site caches; it made no schema changes and needed no rollback.

These checks prove lesson data authorization, assigned-course visibility and
the delivered frontend revision. External video playback was not re-tested.
Personal records, identifiers, session values, backups, logs and journal events
remain in private operational storage and are not included in this repository.

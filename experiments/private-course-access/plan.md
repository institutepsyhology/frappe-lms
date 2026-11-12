# Implementation and verification

1. Audit current backend, frontend, source staging and live publication counts.
   Course publication controls general visibility; lesson drafts independently
   deny playback. The native personal-grant model remains authoritative.
2. Fix the course-detail redirect for a real backend-provided membership and
   avoid redirecting before loading finishes. Keep unentitled visitors rejected.
   Test the actual Vue component against the installed dependency set.
3. Prepare a bounded trusted MVC-only operator. Preview the exact course/lesson
   changes, then disable self-enrollment and enable only current granted imported
   lessons with All audience, previews off and no modifications to grant lists.
   Use the normal document lifecycle with an explicit publication-action flag,
   per-document readback, private journal, content and access-set invariants.
4. Build and verify an isolated pinned frontend candidate, keep database backups
   and rollback, activate the smallest coherent release and verify three-site
   health. Do not touch the Windows recovery drive or unrelated worktree edits.
5. Apply a small data pilot, verify the allow/deny matrix with actual learner
   context, apply the remaining candidate lessons and recheck invariants.
6. Confirm actual HTTPS behavior, the served frontend revision and counts;
   record reproducible sources and validation results in GitHub.

Publishing every course would make the catalogue public. Keeping every lesson
as a draft prevents the intended learners from studying. The selected approach
uses private course visibility plus explicit existing grants and only removes
the migration staging barrier for lessons already granted.

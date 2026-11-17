# Course access and learner visits

The person/course dialog separates assigned lessons from the remaining course
lessons. A bounded page supports selection and one atomic add/remove operation.
Grant identity, course scope and every selected lesson are validated server-side;
progress and homework are preserved. Multiple grants remain additive, with an
explicit warning: removing one grant's lesson does not remove another grant.

The table separates access availability, scheduled opening, first/last recorded
learner page visits, and completion. A page visit is not proof of video watching
or completion. Historical creation/modification dates are not copied into the
new visit fields. New events are recorded only for enrolled authorized learners;
native staff previews and Frappe sessions marked `impersonated_by` cannot create
these visit dates or video watch updates. Use the platform's staff impersonation
mechanism for support; ordinary login with a learner's credentials cannot reveal
who is holding those credentials.

Course/lesson visibility settings control unavailable titles and a dedicated
block-editor notice. The notice can contain explanatory materials and payment
links. Protected lesson body/media and assessments are not substituted into it.
Draft publication gates still apply. Russian reasons explain blocked, scheduled
and expired access. Retained completed lessons remain usable after expiry;
explicit course blocks deny every lesson. The existing free-order setting is
the inverse of `enforce_lesson_completion`, whose default remains off.

## Reproducible release

Create a context from an exact committed revision with `create_context.py`.
It verifies the existing base tag by image ID before building; the runtime uses
the same LMS/Frappe versions. The Docker build runs relevant backend/component
tests and the production frontend build, without installing packages. Candidate
schema/controller checks run only against the existing isolated stage volumes
and network. Smoke fixtures roll back and never use production learners.

After publishing the tested revision, `release.py prepare` verifies existing
encryption keys and fresh database backups. `release.py activate IMAGE MANIFEST
REVISION CONTEXT` verifies candidate source hashes, current live source hashes,
image labels and baseline before the existing guarded six-service activation.
Only three additive DocType reloads are needed. Service/count/ping failures
restore the previous image; added schema is compatible with image rollback.
Credentials, runtime configuration and database backups remain private.

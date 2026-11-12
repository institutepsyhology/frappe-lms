# Private courses for migrated MVC learners

An enrolled learner must see their migrated courses and open only lessons
allowed by the current AVO access record. A newly registered or unrelated
learner and Guest must not gain those courses or media.

Observed blockers: the importer deliberately sets course.published=0 and every
lesson.is_draft=1; the course detail frontend also redirects enrolled members
away from an unpublished course despite the backend admitting that membership.

Required behavior:

- Keep imported courses unpublished in the general catalogue. My Courses and
  original AVO routes must work for their authenticated members.
- Disable self-enrollment and lesson previews. New accounts receive no implied
  enrollment or personal grant.
- Enable only imported lessons already referenced by verified current Applied
  grants. Unreferenced staged lessons remain drafts. Do not claim the staging
  draft field reproduces unknown original editor draft settings.
- Preserve exact grant lesson sets, dates, freezes, source IDs, content,
  enrollments and learner progress. The public publish-All action must not be
  used: it appends lessons to other learners' grants.
- Check real member allow, wrong-user deny, unassigned-lesson deny and Guest
  deny; verify private catalogue behavior and the frontend membership guard.
- Publish the matching sources/tests/results to the existing GitHub branch and
  verify deployed frontend assets. Keep credentials and personal data private.

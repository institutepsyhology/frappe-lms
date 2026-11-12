# Stable AVO course and lesson URLs

Mapped courses use `/lms/courses/avo/<course-id>` and lessons use
`/lms/courses/avo/<course-id>/lessons/<lesson-id>`. The site determines the
source account; ambiguous IDs and mismatched course/lesson relationships fail
closed. Legacy URLs continue to resolve, and mapped navigation is redirected
to the source-ID route. Frappe document names and enrollments are unchanged.
Lookup checks course and lesson permissions and completion gates. The lesson
read method verifies the actual lesson identity after loading it so a reorder
cannot substitute another lesson. A closed lesson may show the generic
unavailable screen at its ID URL.

The production image at this release differs in three files from the branch:
it lacks some earlier HTML heading and spacer changes. `apply_live_delta.py`
checks exact deployed content hashes and changes only the lines necessary for
this release, so those unrelated features are not accidentally deployed or
removed from the repository. Reconcile those differences before a later release.

On 2026-11-12 image
`sha256:3f6d1884e2dee5dff756a44376214080f89f2e545f24cb8ec1efd878e01d402b`
was deployed from source commit `aab1feee26433374f9b0928ca9588d1a41ce7151`,
replacing `sha256:4c1e2fe27bf2212b39504792f989024e1051e0015761ca5672531018e62728dc`.
Seven backend and 83 frontend tests passed; fresh database backups passed
gzip validation; three sites passed health and nondecreasing-count checks;
both contact workers resumed. Live MCP resolved MV-Centr course 11 and lesson
26, fetched the intended lesson, and round-tripped their IDs. The same pair
did not resolve on IOMP or Master Vision, where those mappings do not exist.
Guest access to the draft returned no mapping; both SPA paths returned HTTP
200. Browser control failed to start, so actual visual rendering was not
verified. Database backup integrity checks are not a restore test.

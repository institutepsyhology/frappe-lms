# Original AVO URLs on the LMS domain

The lesson preview remains at `/personal/training/<course-id>/view/<lesson-id>`.
The editor remains at `/shop/training/traininglessons/admin/update?id=<lesson-id>&lg=ru`.
The course link `/personal/training/<course-id>` selects the existing enrollment
resume pointer or the first accessible mapped lesson. Source IDs are resolved
only within the account belonging to the current site. Duplicate IDs, unavailable
lessons, invalid query IDs and denied edit permission fail closed.

Website route rules serve the SPA at these exact root paths without an HTTP
redirect to an invented URL. Root browser history keeps ordinary LMS pages under
the configured LMS prefix. Login return addresses retain path, query and hash.
Previous internal lesson URLs remain supported; the old edit form continues to
validate both course and lesson IDs. Native course administration keeps its LMS
route. Mapped course cards link directly to the original AVO course path.

The source context comes only from the committed revision. The existing deployed
lesson source has unrelated differences from the repository; a hash-checked
minimal delta preserves those differences. The guarded release reuses fresh
three-site backups, health/count checks and rollback support. DNS and domains
are not part of this change.

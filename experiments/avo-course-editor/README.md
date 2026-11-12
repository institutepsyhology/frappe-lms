# AVO course and lesson addresses

Course cards use their source ID in copyable links. Mapped lessons have separate
view and edit paths. Editors resolve both source IDs in the current account,
check course and lesson permissions, and save by verified document identity.
Ambiguous mappings or changed identities are rejected. Legacy and non-AVO
links remain available. The release applies a checked minimal delta to deployed
files that differ from the repository so unrelated changes remain untouched.

Released 2026-11-12 from source 9cf7c4655e87f87acfea2300e1675cce2b94d7cc
as image sha256:7ea71aa30403ba41266cb7fc3787b964dba949b69130dd9073afad4a89fdb8d2.
Eleven backend tests and 114 frontend tests passed, followed by the production
build. Gzip integrity of fresh database backups was checked. The guarded switch
verified all three sites and nondecreasing record counts; the password worker
was resumed. Browser checks confirmed the old xr route redirects to course 206,
the catalogue exposes a copyable ID link, lesson 809 opens at its ID address,
and its editor and preview link render without browser errors. The excluded
837/7642 test lesson remained unavailable. Unauthenticated editor reads return
HTTP 403. Browser validation did not alter or save an existing lesson; save and
identity checks were exercised by unit tests. Backup checks are not a restore test.

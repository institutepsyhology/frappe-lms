# Production verification, 17 November 2026

Published application revision: `7924cbb54ecb434f3dfe633beeb0c493c3484f02`.
Running image: `sha256:01fbbaeecbd04e4db7af2f6eaf30bd84ed38d5b3270e97c3e47123b59e998573`.
The pinned base retains LMS 2.64.0 and Frappe 16.53.0; no upstream upgrade was made.

The committed build context passed 74 Python unit tests, 99 Vue component tests
and the production Vite build. Its source manifest was checked against candidate
files before activation. The independent GitHub branch readback matched the
application revision.

The isolated MariaDB/controller preflight used the existing stage network and
stage volumes, with no production sites mounted. All 21 roster checks passed
with 205 synthetic learners. Seven additional checks passed: bulk removal keeps
progress, restoration and assigned/available filters, hard course block priority,
staff impersonation creates no visit, learner creates verified visit dates,
free-order access, and completed-lesson retention after expiry. Fixtures rolled
back. The older roster fixture was updated to provide the complete matching
synthetic AVO identity required by the newer contact-binding guard.

Fresh three-site database/key backups were verified before guarded activation.
All six services switched to the candidate, and additive schema reloads passed
on my-lk.mv-centr.ru, my-lk.iomp.ru and my-lk.mastervision.su. Counts did not
decrease, and all three HTTPS pings passed. Previous image/rollback backups
remain available privately.

Post-activation source hashes matched the published source in all six service
containers. Actual MVC MCP reads confirmed the assigned-lesson table responds
with access, schedule, verified-date and completion columns; an old unverified
visit remained blank. The visibility-settings endpoint worked. Independent
native schema reads confirmed the new fields across the three sites.

Visit dates mean authenticated learner page openings, not full video viewing
or homework acceptance. Historical creation/modification timestamps were not
backfilled. Native impersonation markers and staff roles are excluded; use the
platform's staff-entry mechanism rather than logging in with learner credentials.

This receipt reports component and real-controller/API checks. It does not
claim a manual browser visual inspection of the installed account screens.

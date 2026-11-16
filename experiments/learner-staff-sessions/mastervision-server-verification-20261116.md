# Master Vision parallel server collector, 16 November 2026

The owner requested MV account collection beside the existing MVC job, with data
delivered to the corresponding Frappe site. Read-only checks found little laptop
RAM available, while the server had about 1.9 GiB available RAM, 7.7 GiB free disk
and low load. MV therefore runs entirely on the server, initially at one request
per second. MVC's current processes are preserved.

151 synthetic tests passed, with one Unix filesystem-permissions test skipped on
Windows. They include immutable allowlisted account profiles in fresh processes,
default MVC archive/DPAPI compatibility, cross-account rejection, existing-site
server encryption binding, standalone receiver execution, safe key handoff through
stdin pipes, detached launch, duplicate-worker prevention and source-manifest
verification. A layout-specific test ensures a private standalone server release
is accepted while actual Git repositories remain forbidden output locations.

Root review and a separate read-only review found no remaining launch blockers.
An unauthenticated request to the confirmed MV shop's API route returned HTTP 401;
no secret was sent to a guessed AVO alias. The source is fixed to shop.mastervision.su
and the site to my-lk.mastervision.su. All production entry points verify an exact
published source bundle before accepting/using a key. The new job performs only
source archival; existing users, permissions and learner sessions are not modified.

The next live gates are source installation/hash checks, a Linux synthetic
encrypted full pipeline (zero AVO requests/LMS users), local masked key entry,
real MV progress and observed MVC throughput. A server process start alone does
not prove that the source accepted a key or that collection has begun.

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

The exact published bundle 8256ed1d520cd77d7eddfe5cecd1bb2d99c3c74e was installed
under the MV site's private directory and all eight source hashes verified.
The real Linux synthetic pipeline then collected/encrypted/decrypted two fake
contacts and a page using the existing site key, with zero AVO requests and zero
LMS users created. Only its explicitly created synthetic files were removed.

The owner entered the MV GET key in the masked local window. A detached server
worker continued after the SSH/local launcher completed. The subsequent real
read-back showed 8,692 source contacts in 87 encrypted pages, 88 requests and no
source error. The first real page decrypted, matched its saved SHA256 and parsed
to 100 records. Worker RSS was about 140 MiB and the archive about 2.47 MiB.
No source contact payload was written to the laptop; its local state is only
nonsecret process/progress metadata. The API key was not persisted.

MVC's observed rate before MV launch was 59 links/20.02 seconds (2.947/second).
After MV launch it was 58 links/20.02 seconds (2.897/second), with zero failures.
These short observations show no material slowdown; they are not a guarantee
against later provider throttling or changing server load. Both original MVC
processes remained active, and MV began at one request/second on the server.

The MV source contact traversal is still in progress; its final total is not
known yet. Individual-card link verification follows the raw-resource phase.
These observations prove encrypted source retention, not completed creation of
all LMS user cards or activation of the separate legacy-login feature.

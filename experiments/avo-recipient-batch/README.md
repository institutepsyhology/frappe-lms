# Recoverable MV-Centr recipient batches

Selected recipients are imported in batches of up to ten. The server retains
the original per-user checks and commits each accepted user separately. Before
posting a batch, the client records only source IDs in a private checkpoint.
It verifies both AVO IDs and email addresses after each request. If the reply
is lost, it reconciles every ID before retrying absent records. An ambiguous
identity preserves the checkpoint and stops; ten consecutive rejected records
or ten failed recovery attempts also stop the worker. Credentials and contact
data are not written to the checkpoint or the repository.

On 2026-11-12 the guarded release activated image
`sha256:4c1e2fe27bf2212b39504792f989024e1051e0015761ca5672531018e62728dc`
from source `b4af3cb5be776fbb528922b28b82d5afd0243a5f`. The previous image
was `sha256:b43a6d9392ee940bf7f4a74b680ae2e06e400865d505e1e81096821e2217e099`.
Database backups passed gzip checks, all three sites passed health and
nondecreasing-count checks, and the password worker resumed. Synthetic tests
covered selection, opt-outs, interruption, ambiguous matches, retry behavior
and server batch bounds. An actual three-contact pilot passed read-back, and
three more contacts imported by the background worker were independently
checked by source ID and email. At the first post-deployment sample, 200
verifications took about 39 seconds; this is a short observation, not a
guaranteed sustained throughput.

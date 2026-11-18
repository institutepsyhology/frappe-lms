# IOMP batch migration, 18 November 2026

The IOMP source catalog contained 317 courses. The existing isolated Edge
session collected 12 consecutive courses after the verified course 2, for a
total of 163 lesson snapshots. Each complete capture was checked against a
second read of the ordered source outline. A later batch selected the next 30
unresolved courses automatically, including ready captures from the first batch.

Run from this repository root:

```powershell
node experiments/avo-iomp/batch.cjs --capture-only 2 12
node experiments/avo-iomp/batch.cjs --apply 2 30
```

The two numeric arguments are the exclusive starting course ID and the batch
limit. Courses are created as drafts. The client compares
existing drafts with the source order, confirms every new lesson by read-back,
and disables self-enrollment. It validates covers, copies supported images to
Frappe, and records cover problems separately when a copy needs review. JPEG
course covers await separate write/read-back support in this batch client.

The private IOMP `captured` directory contains the complete catalog, lesson
snapshots, `batch-events.jsonl`, and `batch-review.jsonl`. Completed and review
entries are skipped when the next normal batch starts. A `STOP` file pauses
between courses. The job stops on loss of authentication, ten consecutive
course reviews, low local disk space, or an uncertain Frappe write. An uncertain
write requires verified read-back before resuming. The browser profile, source
data, images, contacts and credentials are excluded from Git.

The first live batch hit a cover read-back check on course 7. Frappe had
deduplicated its cover against the same bytes already stored for course 2. The
updated check verified the attachment, file name, local URL, size and hash.
Reconciliation confirmed all three lessons and completed course 7 without
recreating a lesson or file. The subsequent batch imported more courses.

At the live checkpoint around 14:43 Moscow time the journal recorded 22 batch
course completions and 31 lessons. Six courses were set aside for review. The
background process was active. A server filesystem check reported 8.22 GiB free.
Direct read-back of courses 5, 6 and 7 confirmed unpublished drafts, local covers
and self-enrollment disabled. This checkpoint does not cover playback, all 317
courses, or access grants. There was no server software deployment.

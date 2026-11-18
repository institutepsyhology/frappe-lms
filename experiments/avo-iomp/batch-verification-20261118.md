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

The owner confirmed that the standard avatar and the generic greeting should
be omitted. The IOMP import now recognizes the exact standard image with its
default `Изображение` label. It prepares a copy of the parsed payload and leaves
the archived source intact. The existing source fingerprint and exact greeting
checks still guard omissions. A regression test confirmed that a teaching image
with the same default label and a custom caption are preserved.

Rechecking courses 3, 31, 33, and 37 cleared eight avatar-related issues. Course
33 passed preflight and was imported with all 39 lessons in source order as
drafts. IOMP read-back confirmed disabled self-enrollment and found no avatar
or generic greeting in lessons 500 and 516, with their two and four video
choices respectively and timing HTML retained. The latest batch journal now
lists 44 unresolved lessons in 11 courses.

On the next pass the owner supplied ten excluded lesson IDs and corrected
source videos in 827, 896, 897, 1203, and 1331. A bounded refresh read those
lesson editors and 2230 using the IOMP source session. Both video URLs
were already valid in the live 2230 snapshot. Refreshed records are used
only when the verified course outline matches the original archive.

The IOMP preparation retains heading markup and links and removes legacy
presentation metadata from timing tables only after validating their text,
links, and cell order. Exact trainer-question actions and empty audio
buttons are omitted. Lesson 4396 contains two distinct YouTube IDs, a pasted
duplicate of the second player's controls, and two small homework icons.
The source-bound repair keeps both videos, both icons, and the homework text.
Lesson ID 5296 is in the exclusion set. It was absent from these captures.

All 11 recheck courses passed local preflight with 518 included lessons and
nine matched exclusions. Three targeted regression tests passed. The
`node experiments/avo-iomp/batch.cjs --retry-review 2 11` worker then started
writing verified drafts and recording the result for each course. At this
checkpoint course 3 existed as an unpublished draft and its lessons were
still being imported. Source snapshots remain private.

The owner subsequently excluded lesson 4396 and requested lessons 1512,
1792, and 1956 without audio. The IOMP policy records those decisions for
later runs. Lesson 4396 had already been created before the clarification.
It remains a draft in unpublished course 4 with zero enrollments. The
attempt to remove its course membership was denied by the automatic review,
so the local journal records the exclusion and the existing draft separately.
Read-back of 1512, 1792, and 1956 confirmed draft status and no audio blocks
or audio links. The presentation in 1792 was retained.

The review batch completed at 16:07 Moscow time with 10 accepted courses and
517 lessons after excluding course 4 from the active results. No unresolved
lesson issues remained in that batch. The stored draft of lesson 2230 has one
YouTube/Rutube pair. The next batch of 30 began at 18:28 Moscow time, starting
from course 38. Before that launch, available space was 7.95 GiB on the server
and 2.68 GiB on the local drive. The selected MV contact transfer was active.

The batch starting from course 38 finished at 18:45 Moscow time. It added 22
courses and 141 lessons, with eight courses recorded for review. The next
30-course batch was launched starting from course 69 after checking free
space of 7.91 GiB on the server and 2.63 GiB locally.

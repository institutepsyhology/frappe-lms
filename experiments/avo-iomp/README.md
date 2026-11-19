# AVO legacy labelled video pairs

An AVO lesson sometimes has a main video and an alternative as separate blocks,
each preceded by an explicit Russian label. The converter combines the exact
labelled sequence into one player, retains both original URLs and the main
provider, and flags unmatched or modified labels for review. Pairing is limited
to one APE section. Unlabelled independent videos are not paired. Layout and
label reconstruction differences are warnings.

The account and origin are checked against the Frappe site; IOMP is accepted
only on `my-lk.iomp.ru`. An IOMP release also requires the same AVO ID fields as
the other sites; create/verify them separately and do not grant learner access.
Images from APE require supplied, validated private image bytes; the server
never fetches arbitrary source URLs. Source snapshots remain private.

Run `python -m unittest lms.lms.test_avo_transform lms.lms.test_avo_import_unit`
and verify a representative private source locally. Run the release from a
reviewed, published commit archive, without snapshots or private URLs.
`deploy.py` checks the installed production image, the separate base image,
builds a single-layer overlay, tests it in isolation, backs up all sites,
checks health and unchanged site counts, and rolls back on failure. After
release verify the actual MCP transport, isolation, dry-run and browser player.
Document any limitations and the matching released commit in this repository.

## Release verification, 2026-11-03

Published source `ac74d8b6ea4c9a5dd91c4f8c3bae247e9f8c5dde` produced image
`sha256:3d777da4a1255e0027aa50d8f164918ddc08eab0bef0640c873c3e7d766d1243`.
The candidate passed 21 synthetic backend tests. Integrity checks passed on
fresh database backups; six application services and three sites were healthy,
with unchanged site counts, language, and access-release switches. A backup
integrity check does not demonstrate a restore.

The four identity fields in `lms/lms/avo_mapping_fields.py` were created and
read back on IOMP through its MCP. Synthetic labelled-pair dry runs through the
actual Codex MCP succeeded independently on IOMP, mv-centr and Master Vision.
Synthetic inputs with mismatched IOMP/mv-centr origins were rejected. A changed
label returned `legacy_player_pair_unresolved` and `ready=false`. No real
IOMP lesson or access grant was created by these checks. An IOMP example passed
local conversion using a placeholder for its image, with both original video
URLs retained in one pair. Actual image transfer and playback remain unverified.

## Resuming an IOMP import

IOMP course 346 omits the chat invitation (lesson 7117) and retains 18 lessons.
Course 347 contains the one reviewed masterclass iframe in lesson 7128. Its
native HTML block preserves the original iframe markup and 3100px inner height.
The importer verifies the saved contents, numeric IDs and private outline on
replay. Its source cover is served as PNG but decodes as JPEG.

`node experiments/avo-iomp/batch.cjs --apply 100 317` processes pending courses
above source ID 100. To revisit particular review items or missing covers, use
`--retry-courses 44,48` with the current pending IDs. Both modes use the same
exclusive lock, preserve course order and verify drafts against the IOMP site.
Each course outcome is recorded in the private capture archive. Set `IOMP_PYTHON`
to a Python executable with Pillow for JPEG covers. The importer applies EXIF
orientation before upload and checks the saved file size and checksum.

On 19 November 2026, stored material in IOMP drafts 243, 263 and 342 was
compared with the source. The comparisons covered the two handbook links, the
labelled YouTube and VK players with their presentation, and the reading list
with its illustration, video blocks and audio link. These checks covered
persisted content and ordering. They did not exercise video playback.

The batch keeps one IOMP MCP session in memory and processes courses serially.
After a recorded login failure, `--resume-empty COURSE_ID` requires an empty
destination for that course, its source lesson IDs and its expected attachments.
Uncertain writes still require reconciliation.

Course 91 has 62 MP3 attachments across ten lessons. The supervised importer
copies them directly from AVO to IOMP private storage, verifies bytes and
size, then binds each File to its saved draft lesson. A retry validates existing
attachments. The corresponding lessons of course 116 reuse the same audio
after verifying every source reference in order and matching each private File.
Each course retains its original lesson IDs. LMS serves a shared file to a
learner with access to a lesson that contains it.

On 19 November 2026 all 64 drafts of course 91 and all 62 private bindings
were verified. Two actual media links returned the requested byte range
to an administrator and denied it to an anonymous visitor. Access as an
enrolled student was not tested on the unpublished course.

For reviewed IOMP lessons, missing Rutube alternatives can be recovered from
another IOMP lesson after comparing the primary video and its context. The
normalizers read validated source captures at runtime. Repository files store
source fingerprints, not private player URLs.

In the 19 November follow-up, courses 131, 146, 152 and 163 were read back as
drafts. In lessons 2093 and 2411 the empty third audio button was omitted.
Lesson 2249 retained five YouTube players and gained four matching Rutube
alternatives. The individual media URLs, headings and order were compared with
the source. Lessons 345 and 2689 are excluded from future imports. The existing
closed draft of lesson 345 stays ninth in course 60. Retries verify its position
and skip writing it.

All ten lessons of course 172 were verified as drafts in source order. Lesson
2882 uses both YouTube/Rutube pairs and the PowerPoint link from lesson 1886
for “Презентация 1”. The other three material links and the lesson HTML were
checked against the original capture.

IOMP courses 247 and 251 are excluded by owner decision. In course 193 the
importer removes the questionnaire button in lesson 3280. Lesson 3260 keeps
its video pair and audio link and omits the duplicate presentation button.
Reviewed timing blocks preserve their text, list items and links. Lesson 3268
omits the unavailable Google illustration and retains the timecode on that line.
Lesson 202/4096 uses the
approved video pair and audio link from 221/4103. For these two courses a
verified initial sequence can be saved in source order up to the first problem.
The journal keeps the course in review until the rest of the outline is ready.
The owner subsequently excluded the empty lessons 4097–4101 in course 202,
4448 and 4453 in course 237, and 4721–4724 in course 261. Their expected
outlines contain 43, 24 and 17 lessons, respectively.

Course 208 omits the optional sales lesson 3532. Lessons 178/3002, 194/3288
and 207/3498 use the application links from their own student previews. The
importer reads the private `preview-offer-links.json` next to `batch-events.jsonl`
and verifies the school, both source IDs, original button and approved URL
before replacing the editor placeholder. Each stored URL opens the corresponding
anonymous form. Its query contains only `r`, `id`, `clean` and `lg`.

On 19 November the IOMP editor was refreshed for course 305, lesson 5834.
The saved draft contained the exact refreshed YouTube/Rutube pair and audio
link. The 61 draft lesson IDs in courses 301, 302, 303, 305, 306, 308, 309,
310 and 311 matched their respective source outlines in order. For these
courses the importer recognizes the reviewed material captions and static
timing accordions. The owner excluded lesson 5758. Read-back of the unpublished
IOMP course 304 confirmed source IDs 5737, 5738, 5743, 5744, 5745 and 5746
in that order, with public lesson previews disabled. The importer ignores
standalone, unlinked `{avatar_url}` placeholders, retaining their siblings.
It recognizes the same audited audio and material captions across IOMP,
preserving the original HTTPS destinations.

Course 332 lesson 6154 has the same source content as 146/2249. Its five
YouTube videos were read back in order, four with matching Rutube alternatives
from other IOMP lessons and the first with YouTube alone. Course 331 lesson
6102 uses plain text for the quoted term «психосоматоз» in its introduction.
Read-back confirmed the introductory HTML, paired player, five
resource links, homework and timing text. The unpublished course outlines
matched all 41 and 68 source IDs respectively.

`plain_term_correction.py` checks the seven existing IOMP copies against
their private source snapshots. With `--apply` it replaces the one affected
block, attaches the revised import snapshot and verifies the complete lesson
through the regular importer. It can be rerun after an interruption.

For IOMP lessons pasted from an office document, the importer removes the
serialized clipboard class on paragraph tags and the observed office tab-stop
attribute only after the remaining HTML passes validation. It keeps the text,
links and author formatting. Static timing panels retain each heading followed
by its original content. Multiline simple headings keep the heading level and
line breaks. Outer whitespace on a single player URL is trimmed only when
the resulting address passes the validator for the same provider.

Read-back of lessons 4733, 5943 and 2954 checked the copied text and links,
the two multiline headings and the timing panel titles, respectively. Their
course outlines matched the source order.

Course 221 was imported after refreshing lesson 3817 from AVO. Read-back
confirmed the original order of all 12 drafts and both primary YouTube and
alternative Rutube URLs in one player in the eighth lesson.

Lessons 232/4299, 233/4298 and 253/4546 retain native certificate buttons with
the original AVO personal certificate URL and new-tab behavior. Historical
countdowns with the reviewed June 2024 deadline show the four zero values
observed in AVO. Certificate issuance and existing learner access are independent.

# IOMP course 2 import, 18 November 2026

The operator signed into `shop.iomp.ru` in an isolated Edge profile. The
collector read course 2 and lesson editors 2, 3, and 4 sequentially. A second
course-editor read confirmed the same titles and lesson order. The collector
archives editor settings and decoded lesson blocks under the IOMP export folder.

```powershell
node experiments/avo-iomp/login.cjs
node experiments/avo-iomp/capture_course.cjs 2 5
```

The first capture exposed an encoding mismatch in the Windows Python input
pipe. The parser now decodes UTF-8 explicitly. A second live capture verified
the Russian titles, and a regression test runs the parser with a CP1251 console.
The source suite passed 33 tests, including rejection of cross-account links.

All three lessons passed an MCP dry run before the first write. The live read-back
on `my-lk.iomp.ru` verified the following:

- One unpublished course with AVO and LMS ID 2.
- Three draft lessons with AVO and LMS IDs 2, 3, and 4, in that order.
- Exact saved video URLs for four YouTube entries and original URLs for four
  audio materials. Frappe added the safe `rel` attribute to the audio links.
- Original PNG cover attached as a local Frappe file. The stored size and
  content hash match the validated original.
- Self-enrollment disabled, zero course enrollments, and editor routes for
  each original lesson ID resolved to the verified positions.

The converter omitted the standard greeting and placeholder image and placed
blocks sequentially. Source settings remain in the private archive. This check
covers saved content, draft flags, order, and route resolution. Playback and
external audio availability remain unverified. No server deployment was needed.
The repository contains the parser and migration record, separate from source
content, account credentials, or browser profiles.

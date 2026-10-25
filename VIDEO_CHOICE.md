# Video source choice inside a lesson

The `videoChoice` EditorJS block lets a student switch between Rutube and YouTube without opening a video page. It renders two provider buttons and one responsive iframe. Switching removes the previous iframe, stopping its browsing context and playback. The initial provider defaults to Rutube; the student's selection does not change the author's saved default.

The author can edit both source URLs and the initial provider inside the block. Both the lesson editor and student renderer use the same registration in `getEditorTools()`. The old Markdown body must be cleared when migrating a lesson to this JSON block so stale external links cannot reappear.

## Stored data

Example only; IDs and access key below are fictitious:

```json
{
  "blocks": [{
    "type": "videoChoice",
    "data": {
      "rutube": "https://rutube.ru/play/embed/0123456789abcdef0123456789abcdef/?p=fake_test_key",
      "youtube": "https://www.youtube.com/embed/abcdefghijk",
      "defaultProvider": "rutube"
    }
  }],
  "version": "2.29.0"
}
```

Actual media URLs and private access keys remain in authorized LMS content and server-only backups. Never commit them. This repository contains neither the private source manifest nor the pre-change lesson backup.

## Validation and navigation

The block accepts HTTPS source or embed URLs on exact provider domains, validates individual video IDs and converts them to player URLs. Private Rutube source URLs require their `p` key; the key is preserved in the embed. Userinfo, unrecognized ports, unsupported paths and lookalike domains are rejected. URLs are assigned through DOM attributes, never interpolated into HTML.

There are no outgoing anchors in the block. The iframe sandbox allows scripts, its own origin and presentation, but does not grant popups or top-level navigation. These are ordinary provider embeds, not DRM; provider branding and browser-level actions are outside the block.

Watch-duration reporting and video-completion enforcement are not integrated with this block. It does not change existing settings or access rules. In particular, do not infer verified watch time from the selector or from the presence of an iframe.

## Tests and release

The targeted suite is `frontend/src/tests/videoChoice.test.ts`. It covers normalization, private-key preservation, rejected URLs, editor save, the read-only view, one iframe, old-player removal, default-provider persistence and navigation restrictions. Fixtures are synthetic.

The release extends the verified local image `company-lms:russian-2.64.0-20261024`, whose required ID is `sha256:35b5b3e30e863b5b4488ee4c60345cebb742cfe4096aa2f582fcd4d62f31229b`. It changes only the tool registration, new block and its test. It installs no dependencies and upgrades no app.

Prepare a new safe context (only six explicitly listed source/release files):

```text
python3 video-choice-build-context.py /NEW/EMPTY/OUTSIDE/CHECKOUT --build
```

The Containerfile runs the full frontend Vitest suite before building the app. After reviewing build results, run the copied `video-choice-deploy.py` alongside `russian-deploy.py` on the existing host. It requires the reviewed old image, backs up the exact runtime environment root-only, recreates only six application services, verifies all three sites and their counts/languages, and rolls back on failure. It performs no content edit or migration.

Before lesson migration, keep a server-only root-readable backup of the existing lesson fields. Update the five intended lessons only, preserve titles/order/access flags, clear `body`, set JSON `content`, and re-read all records through the authenticated application API. Then check the actual lesson editor and student view with both provider buttons and real videos.

Primary implementation references: [EditorJS Tools API](https://editorjs.io/tools-api/), [EditorJS read-only mode](https://editorjs.io/configuration/), [Rutube private-video embedding](https://rutube.ru/info/embed/).

# Link-collector stop and Windows status-file locking

The live job stopped after 1,797 verified personal links with `internal_failure`.
No individual contact was marked failed. Read-only `PRAGMA quick_check` passed;
all 1,797 version/success rows remain, with no dangling member-state references.
The historical log recorded no exception class or OS code, so its exact original
cause cannot be established retrospectively.

A concrete defect was reproduced separately on synthetic files: an ordinary
reader holding `progress.json` makes the old atomic replacement raise Windows
PermissionError (WinError 5). The GUI uses that kind of reader. The old control
flow converts such a status-write failure into the observed generic fatal state
even after the link transaction has committed. This is a verified defect and
plausible explanation, not proof of the historical exception.

The shared progress writer now retries short Windows sharing/access failures
with bounded delays. The bounded reader also tolerates transient replacement
locks. Permanent locks stop with an explicit fixed code; disk-full errors are
not silently retried. Both archive and link phases use the same status I/O.

The link database gains additive safe diagnostics: stage, exception class,
errno and WinError only. Exception text, tracebacks, URLs, contact values and
API keys are not stored. No AVO or Frappe data was changed.

Verification includes real Windows reader-lock reproduction/release, persistent
lock bounds, atomic status preservation, disk-full handling, 500 concurrent
counter updates/GUI reads, diagnostic privacy and resuming after a failure that
occurs after the link transaction commits. Existing successful contacts are
skipped on resume.

All 79 synthetic tests pass after these changes, including the concurrent
reader/writer stress check. The previous stopped archive was inspected only;
no saved link was removed or decrypted into a public report.

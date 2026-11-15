# Accelerate personal-link collection

The live collector is healthy at about one contact/second, with an artificial
one-request/second limit. The owner requested acceleration. Keep the current
single writer, verified source association, encryption, append-only versions,
stop rules and existing archive metadata unchanged.

Use a sequential adaptive ceiling of three requests/second for the GUI's link
phase. Keep the core's default one/second for compatibility; permit a bounded
operator ceiling up to five/second without claiming a documented provider
allowance. Reduce speed on throttling/network/5xx errors and obey Retry-After
across all following attempts/contacts. Recover gradually after clean requests.

Read a small local `speed.json` in the existing link output directory so future
adjustments need no restart/key entry. Malformed settings retain the last valid
rate. A higher setting must never shorten provider backoff. Do not put rate in
strict archive metadata; old successful contacts remain resumable.

Test rate spacing, mid-wait changes, backoff after the final failed attempt,
adaptive decrease/recovery, malformed settings and old-archive resume. Publish
the exact tested sources. Only then gracefully stop the old process, remove
the operator-created stop marker, launch the new version and request a local
masked key entry. Verify real saved-count throughput before quoting a speedup.

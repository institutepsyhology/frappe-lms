# Personal-link speed update, 16 November 2026

The running job had no contact errors and was limited by a client-side
one-request/second ceiling. The owner requested acceleration. The update uses
the same sequential request/validation/encryption/commit flow and does not add
parallel SQLite writers, change accounts or change Frappe data.

The GUI now explicitly passes a three-request/second ceiling to its link phase.
The core default remains one/second for compatibility. Target speed and adaptive
ceiling are separate: retryable failures reduce the latter, clean responses
restore it gradually, and local speed changes never shorten mandatory server
backoff. A bounded private `speed.json` allows later adjustments without
restarting or re-entering the key. The upper five/second bound is a client
guardrail, not an asserted documented allowance of the legacy API.

90 synthetic regression tests passed. New checks cover three/second spacing,
live increases and decreases during waits, final-attempt Retry-After, unchanged
settings and down/up settings after throttling, malformed controls, explicit GUI
rate forwarding, privacy-safe display and resuming an unchanged old archive.
The raw-resource wait also avoids negative sleep intervals after stop checks.

After source commit c631e11 was verified on the remote branch, the old worker
was stopped gracefully using an exclusively created, operation-owned STOP
marker. All 10,883 verified records were preserved. Only that marker and the
identified old GUI process were removed. The new GUI was confirmed visible and
responding; the owner supplied the key in its masked local field.

Live continuation skipped all 10,883 stored successes. A 25.02-second observation
then advanced from 11,211 to 11,283 verified links: 72 new records, or 2.878/second.
The configured/current ceilings were both 3/second, with zero failed contacts,
zero consecutive failures and no speed-setting warning. This is about 2.9 times
the previous observed one/second rate, rather than an inference from the limit.
The same background job continues; future throughput depends on API responses
and automatic throttling. The two pre-existing raw subscription-resource errors
remain separate from the healthy personal-link phase. No Frappe data changed.

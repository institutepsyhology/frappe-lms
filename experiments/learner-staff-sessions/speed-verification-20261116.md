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

The old live worker continues at one/second until the tested source is published
and a graceful handoff is performed. A single new local masked key entry is
needed because the old process does not have live speed-control support and
never persisted its key. Actual throughput must be measured after activation;
configured ceilings alone do not prove a speedup.

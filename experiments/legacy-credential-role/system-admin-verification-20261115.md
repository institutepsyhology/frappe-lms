# System administrator position attachment: verified 15 November 2026

The owner explicitly chose to retain the selected account's existing framework
authority while assigning its business position. This differs from the earlier
retired-password-marker migration.

Application revision: `b279337761b7751265dfdf893d95009de0c514ad`.
Running image:
`sha256:8a7e5a581ebe740fc1767aba07ddbed5c88a2be36e4ac93cf8c58467b5d3227c`.

Verification:

- 126 Python regression tests passed in the built candidate.
- Isolated real-controller checks confirmed both ordinary legacy migration and
  System Manager assignment without rewriting User or its Role Profiles.
- Existing delegation tests still pass, including self/upward escalation
  rejection, hierarchy ceilings and transaction lock release. Delegated staff
  cannot reassign or disable technical administrator accounts.
- Compiled frontend and HTML hashes match the previous image. The source
  manifest matches the published revision; the image has 51 layers, retaining
  the pinned first 50. No frontend recompile or schema change was required.
- Fresh three-site backups and existing keys were verified. Six-service health,
  HTTP pings and non-decreasing record-count checks passed after activation.

The requested live assignment and a repeat save both succeeded through native
MCP. Employee read-back confirmed the chosen position and enabled login. Exact
private before/after comparison showed every pre-existing role and profile,
the User modification timestamp, user type and login status unchanged. The
business position now supplies the intended application management and
credential-read capabilities. No password value was fetched.

Framework authority on an existing technical administrator is independent of
the business-position capability matrix. This patch preserves existing system
roles; it never grants such roles to a new employee or adds them to a position.
Actual identities, source-role snapshots and private receipts are excluded
from this public record. This receipt is a documentation-only follow-up.

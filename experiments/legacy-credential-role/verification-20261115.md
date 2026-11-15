# Retired credential-role fix: production verification

Application revision: `722522d1b7457d3d8cd767e740874b659ebde992`.
Running image:
`sha256:1593e8f40756f5f383ce71a5344adb84da5b12a00c4cea20ea43bb45ede81008`.
The prior image remains available for rollback.

Validation:

- 123 Python regression tests passed in the candidate build.
- Real isolated-stage legacy migration checks passed: the retired marker is
  removed, resulting roles match the selected position, credential-read can be
  both granted and withheld by its matrix, and System Manager remains guarded.
- The existing 16 real staff delegation/controller checks passed, including
  self-escalation denial, actor/parent ceilings and lock release.
- All candidate source hashes matched the published manifest. The complete
  compiled frontend/HTML hash map matched the previous image. The candidate
  has the same pinned first 50 layers and one overlay layer (51 total).
- Fresh backups and existing keys were verified. All six services are healthy;
  all three sites respond to HTTP pings and their record counts did not fall.
  This patch changed no schema.

The requested live staff assignment was successfully retried through native
MCP and independently read back from the paginated employee API. As the actual
employee, server checks confirmed contact read and credential read, removal
of the obsolete marker, exact position-native roles, and denial of self-role
escalation. The real student-card API returned permission to reveal a stored
password. No password value was requested during verification.

User identities, position IDs and private deployment receipts are deliberately
excluded from this public record. The earlier menu-discovery question was
resolved by the owner; no navigation or unrelated frontend change was shipped.
This receipt is documentation only and does not require another image build.

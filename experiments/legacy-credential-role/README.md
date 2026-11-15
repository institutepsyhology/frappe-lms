# Retired credential-role assignment compatibility

Assigning an existing moderator to an explicit position failed when the old
direct `LMS Credential Manager` role remained on the account. That marker no
longer grants credential authority: explicit position capabilities take
precedence, and the older fallback checks Role Profiles rather than this role.

Administrator may now normalize this one retired marker while assigning the
selected position. The resulting native roles are exactly those of the
position, and credential read/write/send permissions come from its matrix.
The marker is not retained, newly granted or delegated. Non-administrators do
not gain this exception; genuine technical roles such as System Manager still
block conversion through this bounded interface.

Three regression tests cover administrator migration, non-administrator denial
and the real-system-role ceiling. The isolated-stage smoke additionally checks
both allowed and denied credential-read matrices against real User saves and
ensures a refused technical-role assignment is rolled back.

The production image is rebuilt from the pinned 50-layer base into 51 layers.
The frontend is unchanged: committed frontend sources must match the prior
tested revision, and compiled assets/HTML are copied from the prior image and
compared by complete file hash maps before activation. This backend patch does
not require another frontend compilation. The guarded release uses fresh
three-site backups, existing encryption-key checks, service health, record
counts and pings, with the previous image retained for rollback.

No real user details, role assignments, passwords or connection files belong
in this repository. Live application-specific read-back stays private.

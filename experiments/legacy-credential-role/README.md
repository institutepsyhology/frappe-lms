# Retired credential-role assignment compatibility

Assigning an existing moderator to an explicit position failed when the old
direct `LMS Credential Manager` role remained on the account. That marker no
longer grants credential authority: explicit position capabilities take
precedence, and the older fallback checks Role Profiles rather than this role.

Administrator may now normalize this one retired marker while assigning the
selected position. The resulting native roles are exactly those of the
position, and credential read/write/send permissions come from its matrix.
The marker is not retained, newly granted or delegated on ordinary accounts.
Non-administrators do not gain this exception.

An existing System Manager account has a separate framework authority. The
owner explicitly chose to preserve it while attaching a business position.
Only Administrator may attach/reassign/disable such an account. Every existing
system role, Role Profile, user type and security setting is preserved, and
User is not saved at all when its login status is unchanged. The position's
application capability matrix applies separately; system roles are not granted
or delegated through that matrix. Disabling employee login remains an explicit
Administrator action and does not delete the account's role history.

Three regression tests cover administrator migration, non-administrator denial
and protection of system accounts from delegated staff. The isolated-stage
smoke additionally checks allowed/denied credential-read matrices and exact
system Role Profile preservation without rewriting the User record.

The production image is rebuilt from the pinned 50-layer base into 51 layers.
The frontend is unchanged: committed frontend sources must match the prior
tested revision, and compiled assets/HTML are copied from the prior image and
compared by complete file hash maps before activation. This backend patch does
not require another frontend compilation. The guarded release uses fresh
three-site backups, existing encryption-key checks, service health, record
counts and pings, with the previous image retained for rollback.

No real user details, role assignments, passwords or connection files belong
in this repository. Live application-specific read-back stays private.

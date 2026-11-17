# Docker build-cache cleanup - 17 November 2026

The owner asked to free server storage during the selected Master Vision contact
migration. Cleanup followed the existing build-cache-only maintenance procedure.
There was no application code, configuration, database, or image deployment.

## Operation

Preflight found no active Docker build/bake/buildctl CLI process. The supported
Docker command was:

```sh
docker buildx prune --builder default --all --force
```

Completed at 2026-11-17T20:50:44.845704+00:00; observed maintenance/check duration was
51.97 seconds.

| Measurement | Before | After |
|---|---:|---:|
| Available filesystem space | 3.71 GiB | 9.11 GiB |
| Build-cache records | 74 | 0 |

Actual net filesystem space recovered: **5.40 GiB**
(5799198720 bytes). Docker reported 9.97 GB in logical cache
accounting. The initial cache inventory classified about 1 GB as unshared; this
was not a reliable estimate of physical bytes recovered. Filesystem measurements
above are the verified capacity result, including concurrent migration writes.

## Verification

- All 18 container IDs, image IDs, running/OOM states and start times were
  identical before and after cleanup. No container restarted.
- Exact Docker image-ID set was unchanged (178 IDs with `image ls -a`,
  including intermediate images); current and rollback images remain available.
- All 16 named/anonymous Docker volumes were unchanged.
- Public HTTPS ping returned `pong` for MVC, Master Vision and IOMP.
- The same two selected-MV worker PIDs remained alive: application stayed applying
  and the individual API collector stayed collecting. During the checked window,
  created users increased by 80 and verified links increased by 217. The collector
  reported zero failed contacts and zero consecutive failures.
- Read-back from the default builder returned zero build-cache records.

No image/container/volume pruning, journal truncation, package-cache cleanup,
backup deletion, application restart, or database maintenance was performed.
No laptop files or recovery drive were touched. Future builds can recreate cache
and may take longer on their first run. This operation is not a completion claim
for the ongoing contact migration, and no recurring cleanup was scheduled.

This record contains only aggregate maintenance measurements and public commands;
no passwords, tokens, personal URLs, contact records, or private configuration.

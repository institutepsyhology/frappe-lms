# Docker build-cache cleanup — 15 November 2026

The owner authorized clearing the build cache after reviewing the disk audit.
This operation changed cache state only; no application deployment was needed.

Preflight confirmed the default Docker-backed builder and no active build CLI
process. The supported command used was:

```sh
docker buildx prune --builder default --all --force
```

Completed at 2026-11-15T09:17:59.941517+00:00 (12:17 Moscow time).

| Measurement | Before | After |
|---|---:|---:|
| Available filesystem space | 5.07 GiB | 13.11 GiB |
| Used filesystem space | 42.22 GiB | 34.19 GiB |
| Build-cache records | 86 | 0 |
| Docker-reported build-cache logical size | 13.78 GB | 0 B |

Actual filesystem space gained: **8.03 GiB**
(8626130944 bytes). Docker's 13.78 GB cleanup total is a logical cache
accounting figure; shared image layers and compressed storage mean it is not
identical to physical filesystem space gained.

Post-cleanup checks:

- Exact Docker image-ID set unchanged; Docker reports 129 images.
- All 16 named/anonymous volumes retained.
- All 18 container identities, image IDs, running/OOM state and start times
  unchanged: no container was restarted for this operation.
- Public HTTP pings return `pong` for MVC, Master Vision and IOMP.
- Build cache is empty. Image/volume/container pruning, database operations and
  backup deletion were not invoked.

The maintenance record contains no credentials, database contents, personal
records or private runtime configuration. Subsequent builds may recreate cache
and take longer on the first run. No recurring cleanup was scheduled.

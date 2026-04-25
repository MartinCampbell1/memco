Historical document. Not current verdict.
Current verdict: see docs/CURRENT_STATUS.md

# Docker Engine Recovery Notes For Memco Postgres Validation

Date: 2026-04-22

This is an archival note only.

It is not part of the current recommended Memco workflow on this machine.

## Summary

This document records the Docker Desktop recovery/debug path that was needed before Docker-based Memco validation worked on this machine.

It is no longer the primary recommended runtime path for Memco on this machine.

## Root Cause Found During Recovery

Docker Desktop backend logs report:

- Docker engine state: `stopped`
- startup failure while ensuring VM disk
- missing disk target for Docker Desktop VM image

Relevant path:

- symlink in local Docker Desktop data:
  - `~/Library/Containers/com.docker.docker/Data/vms/0/data/Docker.raw`
- current symlink target:
  - `/Volumes/MartinAppOffload/Users/martin/Library/Containers/com.docker.docker/Data/vms/0/data/Docker.raw`

Current state:

- `/Volumes/MartinAppOffload` is not mounted
- the symlink target does not exist

Because of that, Docker Desktop cannot bring up the Linux engine.

## Evidence Collected During Recovery

- `docker desktop status` -> `Status: stopped`
- bounded `docker info` probe -> timed out
- `docker desktop restart --timeout 20` -> `Docker Desktop is still starting: context deadline exceeded`
- backend log shows:
  - `engine linux/virtualization-framework failed to start`
  - `open .../Docker.raw: no such file or directory`

## Recovery Attempt In This Session

Safe reversible step taken:

- backed up the dangling symlink as:
  - `~/Library/Containers/com.docker.docker/Data/vms/0/data/Docker.raw.offload-link`
- left the canonical `Docker.raw` path free so Docker Desktop could recreate a local disk image

Observed result:

- Docker Desktop was able to recreate a new local `Docker.raw`
- Docker engine came up far enough to:
  - answer `docker info`
  - build the Memco API image
  - start `memco-db-1`
  - start `memco-api-1`

But:

- the Docker engine did not remain stable enough to use as a trusted day-to-day validation path in this session
- later probes returned to daemon unavailability again

So the Docker path was recoverable enough to validate once, but it is still not a good default workflow on this machine.

## Safe Next Options If Docker Is Explicitly Reopened Again

### Option 0. Do not use Docker on this machine

If you simply do not want Docker Desktop on this Mac:

- keep the private SQLite release path
- or use the no-Docker Postgres path documented in:
  - [2026-04-22_postgres_without_docker.md](2026-04-22_postgres_without_docker.md)

This avoids the Docker-specific recovery path entirely.

### Option 1. Restore the expected volume

If `MartinAppOffload` is an external or offloaded volume that should exist:

- mount or reconnect that volume
- verify the target file exists:
  - `/Volumes/MartinAppOffload/Users/martin/Library/Containers/com.docker.docker/Data/vms/0/data/Docker.raw`
- then, only as a historical recovery path, retry:

```bash
docker desktop restart --timeout 30
docker info
docker compose up -d --build
curl http://127.0.0.1:8788/health
```

### Option 2. Recreate Docker Desktop VM disk

If the original `Docker.raw` is gone for good, Docker Desktop may need a new VM disk.

Important:

- this can destroy existing local Docker images/containers/volumes if handled by reset/recreate
- that choice was not executed in this session

Use this path only deliberately.

## What Was Verified Despite The Blocker

- `docker-compose.yml` is structurally valid
- `Dockerfile` exists
- Postgres migration file exists
- Memco runtime/config/docs support the Postgres path
- local SQLite/private-slice regressions remain green

## Current Memco Impact

- Private single-user SQLite release path: green
- No-Docker Postgres path: green and preferred on this machine
- Docker Compose path: archival-only from the standpoint of the current machine workflow

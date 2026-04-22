# Memco Postgres Without Docker

Date: 2026-04-22

## Summary

Memco no longer requires Docker as the only way to use PostgreSQL.

PostgreSQL is the primary storage contract for the repo-local runtime.
SQLite remains only as a local fallback/dev path and is not the canonical storage contract.

The code supports:

- `MEMCO_STORAGE_ENGINE=postgres`
- `MEMCO_DATABASE_URL=postgresql://...`

So you can run Memco against:

- a locally installed Postgres server
- a remote Postgres instance
- a managed Postgres service

without Docker Compose.

## Required Environment

Set:

```bash
export MEMCO_STORAGE_ENGINE=postgres
export MEMCO_DATABASE_URL='postgresql://USER:PASSWORD@HOST:5432/DBNAME'
```

Optional:

```bash
export MEMCO_ROOT=/absolute/path/to/memco-runtime
export MEMCO_API_HOST=127.0.0.1
export MEMCO_API_PORT=8788
```

## Basic Commands

Bootstrap a persistent database:

```bash
MEMCO_DATABASE_URL='postgresql://USER@127.0.0.1:5432/postgres' \
uv run memco postgres-bootstrap memco_db --root "$MEMCO_ROOT"
```

Then initialize runtime + schema/migrations:

```bash
uv run memco init-db --root "$MEMCO_ROOT"
```

Start the API:

```bash
uv run memco-api
```

Health check:

```bash
curl http://127.0.0.1:8788/health
```

Expected health fields:

- `"storage_engine": "postgres"`
- `"database_target": "postgresql://..."`

## Reproducible Smoke

From a running local Postgres server:

```bash
MEMCO_DATABASE_URL='postgresql://USER@127.0.0.1:5432/postgres' \
uv run memco postgres-smoke
```

What it does:

- creates a temporary database
- starts `memco-api` against that database
- waits for `/health`
- verifies `schema_migrations`
- terminates the API
- drops the temporary database

Optional automated test on machines with local Postgres:

```bash
uv run pytest -q tests/test_postgres_live_smoke.py
```

## What This Path Gives You

- no Docker Desktop memory/battery overhead
- the same Postgres-aware runtime path the repo now supports
- the same migration/bootstrap entrypoint used by the app runtime

## What It Does Not Yet Prove Automatically

- a packaged local Postgres installer flow on this machine
- a full end-to-end automated live Postgres smoke in CI

Those remain separate follow-up tasks.

## Current Recommendation

If you dislike Docker on this machine, this is the intended path.

Docker artifacts may remain in the repo for spec-convergence work, but they are not part of the recommended local workflow on this machine.

## Live Proof From This Session

Validated in this session:

- started Memco with:
  - `MEMCO_STORAGE_ENGINE=postgres`
  - `MEMCO_DATABASE_URL=postgresql://martin@127.0.0.1:5432/memco_local`
  - `MEMCO_API_PORT=8790`
- `/health` returned:
  - `"storage_engine": "postgres"`
  - `"database_target": "postgresql://martin@127.0.0.1:5432/memco_local"`
- `schema_migrations` row count in `memco_local` = `1`
- reproducible smoke script passed against local Postgres maintenance DB:
  - `MEMCO_DATABASE_URL='postgresql://martin@127.0.0.1:5432/postgres' uv run memco postgres-smoke`
- persistent database bootstrap command returned the expected runtime URL:
  - `MEMCO_DATABASE_URL='postgresql://martin@127.0.0.1:5432/postgres' uv run memco postgres-bootstrap memco_persistent_test --root /tmp/memco-postgres-persistent`
- optional live test also passed on this machine:
  - `uv run pytest -q tests/test_postgres_live_smoke.py`
- canonical Postgres release gate also passed and can be persisted with:
  - `uv run memco release-check --project-root /Users/martin/memco --postgres-database-url 'postgresql://martin@127.0.0.1:5432/postgres' --output /Users/martin/memco/var/reports/release-check-postgres-current.json`
- strict benchmark-backed quality gate can also be persisted with:
  - `uv run memco strict-release-check --project-root /Users/martin/memco --postgres-database-url 'postgresql://martin@127.0.0.1:5432/postgres' --output /Users/martin/memco/var/reports/strict-release-check-current.json`
  - benchmark artifact:
    - `/Users/martin/memco/var/reports/benchmark-current.json`

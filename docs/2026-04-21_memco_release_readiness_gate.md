# Memco Release Readiness Gate

Date: 2026-04-21
Last refreshed: 2026-04-22
Status: active current repo-local release gate

## Current Verdict

| Gate | Status | Meaning |
|---|---|---|
| Current target contract | GO | For current repo-local work, the accepted target contract is `docs/synthius_mem_execution_brief.md`. |
| Private release readiness | GO | The current local single-user slice is ready for a technical private owner/operator. |
| No-Docker Postgres operational readiness | GO | The repo has a verified Postgres runtime path on this machine without Docker. |

This document is the active current release gate for repo-local work, despite the original filename date.

Historical original-brief status is tracked separately in:

- [2026-04-22_memco_original_brief_status.md](2026-04-22_memco_original_brief_status.md)

Use it to answer:

- what contract current repo-local work is actually targeting
- whether the private local release is ready today
- whether the no-Docker Postgres operating path is ready today
- and where to look if someone specifically asks the historical original-brief question

Do not collapse these two answers into one.

Related contract decision:

- [2026-04-22_memco_contract_decision.md](2026-04-22_memco_contract_decision.md)
- [2026-04-22_memco_original_brief_track_decision.md](2026-04-22_memco_original_brief_track_decision.md)
- [2026-04-22_memco_original_brief_status.md](2026-04-22_memco_original_brief_status.md)
- [2026-04-22_memco_repo_local_status_snapshot.md](2026-04-22_memco_repo_local_status_snapshot.md)

## Private Release Readiness

Current status: `GO`

This `GO` assumes the current Stage A actor exception:

- owner-only local usage
- simple shared-token/dev-local access
- private local workflows can still run through the CLI/local path without the public API actor payload

What is green:

- clean runtime bootstrap
- JSON import
- plaintext import
- person mapping / speaker resolution
- candidate extraction
- publish
- retrieve
- refusal on unsupported claims
- rollback correctness for superseded current-state facts
- redacted retrieval logs
- CLI-only operator flow from clean root
- acceptance-style eval artifact for the private slice

Primary evidence:

- [docs/2026-04-21_memco_private_release_gate.md](docs/2026-04-21_memco_private_release_gate.md) (`Phase 8 Private Gate`)
- [README.md](../README.md)
- [IMPLEMENTATION_NOTES.md](../IMPLEMENTATION_NOTES.md)

Verification commands:

```bash
uv run memco release-check
uv run memco release-check --project-root /absolute/path/to/memco
uv run memco release-check --output /absolute/path/to/release-check.json

# Optional no-Docker Postgres verification inside the same gate:
uv run memco release-check --postgres-database-url 'postgresql://USER@127.0.0.1:5432/postgres'

# Equivalent expanded commands:
uv run pytest -q \
  tests/test_ingest_service.py \
  tests/test_cli_smoke.py \
  tests/test_retrieval_logging.py \
  tests/test_fact_lifecycle_rollback.py \
  tests/test_docs_contract.py

tmpdir=$(mktemp -d)
uv run memco eval-run --root "$tmpdir"
```

Quick contract-facing regression stack:

```bash
uv run pytest -q \
  tests/test_docs_contract.py \
  tests/test_release_check.py \
  tests/test_cli_release_check.py \
  tests/test_config.py \
  tests/test_llm_provider.py
```

Local artifact refresh shortcut:

```bash
uv run memco local-artifacts-refresh --project-root /Users/martin/memco
```

Most recent recorded evidence:

- contract-facing regression stack:
  - `46 passed`
- active repo-local release-check pytest gate: `47 passed`
- expanded eval artifact on clean root: `total=24`, `passed=24`, `pass_rate=1.0`, `token_accounting.status=tracked`
- full local test suite: `266 passed`
- no-Docker Postgres live proof:
  - `uv run memco-api` with `MEMCO_STORAGE_ENGINE=postgres`
  - `/health` returned `storage_engine=postgres`
  - `schema_migrations` count in `memco_local` = `1`
- reproducible no-Docker Postgres smoke:
  - `MEMCO_DATABASE_URL='postgresql://USER@127.0.0.1:5432/postgres' uv run memco postgres-smoke`
  - passed against a fresh temporary database
- optional live no-Docker Postgres test:
  - `uv run pytest -q tests/test_postgres_live_smoke.py`
  - passed on this machine
- CI workflow bootstrap:
  - `.github/workflows/ci.yml`
  - validated locally with `uv sync --frozen --extra dev --extra parsers`
  - `uv run pytest -q` passed after sync
  - the workflow eval-only gate step passed after sync via `run_release_check(include_pytest=False, include_eval=True)`
- active local release-check entrypoint:
  - `uv run memco release-check`
  - passed locally against the quick repo-local gate
  - latest local artifact:
    - `pytest_gate`: `47 passed`
    - `acceptance_artifact`: `24/24 passed`
    - saved artifact:
      - `var/reports/release-check-current.json`
  - implementation note:
    - the temporary acceptance root intentionally uses SQLite fallback when no local runtime config exists there
    - `--postgres-database-url ...` upgrades the command into the canonical Postgres gate rather than adding a cosmetic smoke-only suffix
  - repo-root resolution:
    - defaults to the nearest Memco checkout above the current working directory
    - can be overridden with `--project-root /absolute/path/to/memco`
  - artifact persistence:
    - `uv run memco release-check --output /absolute/path/to/release-check.json`
    - passed locally and wrote the combined gate artifact to disk
  - canonical no-Docker Postgres variant:
    - `uv run memco release-check --postgres-database-url 'postgresql://USER@127.0.0.1:5432/postgres'`
    - passed locally and produced a single artifact with `pytest_gate`, `acceptance_artifact` on Postgres, and `postgres_smoke`
    - latest saved artifact:
      - `var/reports/release-check-postgres-current.json`
  - strict benchmark-backed quality variant:
    - `uv run memco strict-release-check --postgres-database-url 'postgresql://USER@127.0.0.1:5432/postgres'`
    - this is the gate to use for the full quality claim once benchmark thresholds matter
    - latest saved artifacts:
      - `var/reports/strict-release-check-current.json`
      - `var/reports/benchmark-current.json`
  - local artifact refresh:
    - `uv run memco local-artifacts-refresh --project-root /Users/martin/memco`
    - latest saved artifacts:
      - `var/reports/local-artifacts-refresh-current.json`
      - `var/reports/local-artifacts-refresh-postgres-current.json`

### Private Gate Checklist

This checklist is the current `Phase 8 Private Gate` checklist.

| Private gate item | Status |
|---|---|
| Operator flow | green |
| Rollback correctness | green |
| Refusal correctness | green |
| Person isolation | green |
| Documentation honesty | green |
| Regression coverage | green |

## Strict Original Brief Reference Track

The strict original execution brief is no longer part of the active repo-local release surface.

If someone specifically asks that historical question, use:

- [2026-04-22_memco_original_brief_status.md](2026-04-22_memco_original_brief_status.md)

## Decision Rule

If the question is:

- `Can a private owner/operator use Memco locally today?`
  - answer: `yes`

- `Can I run Memco with Postgres on this machine without Docker today?`
  - answer: `yes`

- `Where should I look for strict original execution-brief status?`
  - answer: `docs/2026-04-22_memco_original_brief_status.md`

## Operational Preference

The preferred operational route on this machine is the no-Docker Postgres path:

- [2026-04-22_postgres_without_docker.md](2026-04-22_postgres_without_docker.md)

Docker artifacts may remain in the repo for spec-convergence work, but they are not part of the recommended local workflow on this machine and should not be used unless explicitly requested.

Historical Docker recovery notes remain here for reference:

- [2026-04-22_docker_engine_blocker.md](2026-04-22_docker_engine_blocker.md)

## Notes

- The private release gate and the strict original-brief track are intentionally separate.
- The accepted target contract for current repo-local work is the repo-local execution brief, documented in [synthius_mem_execution_brief.md](synthius_mem_execution_brief.md) and accepted in [2026-04-22_memco_contract_decision.md](2026-04-22_memco_contract_decision.md).
- The original brief is now tracked as a separate reference/backlog-only line for current repo-local release management, documented in [2026-04-22_memco_original_brief_track_decision.md](2026-04-22_memco_original_brief_track_decision.md).
- The no-Docker Postgres path is intentionally called out separately so it is not conflated with strict original-brief completion.
- Any future claim of strict original-brief readiness must either remove the Docker Compose requirement from the brief or make Docker an explicitly requested part of the accepted workflow again.
- `tests/test_docs_contract.py` is the regression guard for canonical contract-language drift in the active documentation layer.
- `.github/workflows/ci.yml` now enforces the full pytest suite plus an eval-only gate step using the same `run_release_check` helper logic, avoiding duplicated pytest-subset work in CI.
- `memco release-check` is the local executable entrypoint for the active repo-local release gate.
- `memco release-check --postgres-database-url ...` is the optional local executable path for folding no-Docker Postgres smoke into the same release artifact.
- `memco release-check --project-root ...` makes the repo-local tree assumption explicit instead of relying on the package file location.
- `memco release-check --output ...` makes the release artifact reproducibly storable without shell redirection.

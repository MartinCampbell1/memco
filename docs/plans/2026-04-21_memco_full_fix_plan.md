# Memco Full Fix Plan

Date: 2026-04-22
Mode: two-stage
Primary contract document: [../synthius_mem_execution_brief.md](../synthius_mem_execution_brief.md)

## Purpose

This is the canonical repo-local plan artifact for finishing the Memco remediation program without losing the distinction between:

- private single-user readiness
- no-Docker Postgres operational readiness
- strict original-brief readiness

## Current State

Green now:

- supersede rollback correctness
- rollback regression coverage
- private CLI operator flow
- product-contract honesty docs
- private acceptance gate
- expanded eval artifact
- actor-scoped API contract
- provider-agnostic LLM layer
- token accounting
- generic source layer
- stricter candidate lifecycle
- explicit publish gates
- Postgres runtime plus migrations
- verified no-Docker Postgres path

Still open:

- strict original-brief closure while the original brief continues to name Docker Compose explicitly
- ongoing discipline to keep repo-local contract and strict original-brief status separate

## Phase Status

| Phase | Status | Notes |
|---|---|---|
| 1. Critical stabilization | done | rollback bug fixed and guarded by regression tests |
| 2. Honest private release | done | README, implementation notes, CLI flow, private gate all landed |
| 3. Eval and release evidence | done | expanded eval artifact and release gate exist |
| 4. API contract decision | done | actor-scoped API contract is implemented and the repo-local contract decision is now explicit instead of implicit |
| 5. Architectural convergence | done for current repo-local brief | provider adapter, token accounting, source layer all landed |
| 6. Candidate lifecycle hardening | done | stricter lifecycle and publish gates are enforced |
| 7. Infra convergence | done for no-Docker path | Postgres runtime + migrations are green; Docker is not part of the accepted local workflow |
| 8. Final release gate | done for current repo-local release management | repo-local target contract is explicit; private gate is green; strict original-brief track is now reference/backlog-only rather than an active release contract |

## Remaining Work

### R1. Original brief track status

Needed because:

- the original brief still names Docker Compose explicitly
- the repo-local brief now defines the accepted no-Docker contract for this machine

Resolved decision:

1. Current repo-local work targets the repo-local brief documented in [../synthius_mem_execution_brief.md](../synthius_mem_execution_brief.md).
2. Strict original-brief convergence remains a separate explicit track and may only be reopened deliberately.

That decision is recorded in [../2026-04-22_memco_contract_decision.md](../2026-04-22_memco_contract_decision.md).

Current result:

- private release remains `GO`
- no-Docker Postgres remains `GO`
- strict original-brief readiness remains `NO-GO`, but now as a reference/backlog-only track rather than an active repo-local release blocker

### R2. Keep evidence synchronized

Whenever verification changes, update:

- [../2026-04-21_memco_release_readiness_gate.md](../2026-04-21_memco_release_readiness_gate.md)
- [../2026-04-21_memco_private_release_gate.md](../2026-04-21_memco_private_release_gate.md)
- [../README.md](../README.md)
- [../IMPLEMENTATION_NOTES.md](../IMPLEMENTATION_NOTES.md)

### R3. Do not regress into Docker-by-default language

The repo may keep:

- `Dockerfile`
- `docker-compose.yml`
- historical Docker recovery notes

But future docs must not:

- present Docker as the recommended local workflow on this machine
- claim strict original-brief completion unless that question has really been resolved

## Verification Baseline

Most recent verification snapshot:

- `uv run pytest -q` -> `266 passed`
- `MEMCO_DATABASE_URL='postgresql://USER@127.0.0.1:5432/postgres' uv run memco postgres-smoke` -> passed
- `uv run pytest -q tests/test_postgres_live_smoke.py` -> passed on this machine
- `uv run pytest -q tests/test_docs_contract.py` -> `7 passed`
- `uv run pytest -q tests/test_release_check.py tests/test_cli_release_check.py tests/test_docs_contract.py` -> `12 passed`
- `uv run pytest -q tests/test_release_check.py tests/test_cli_release_check.py tests/test_docs_contract.py tests/test_cli_postgres_smoke.py` -> `18 passed`
- `uv sync --frozen --extra dev --extra parsers` -> passed
- `.github/workflows/ci.yml` now runs `uv run pytest -q` plus an eval-only release-check helper step
- `uv run memco release-check` -> passed
- `uv run memco release-check --postgres-database-url 'postgresql://USER@127.0.0.1:5432/postgres'` -> passed

## Next Preferred Step

Use this order:

1. treat [../synthius_mem_execution_brief.md](../synthius_mem_execution_brief.md) as the current repo-local iteration contract
2. preserve `strict original brief` as a separate reference/backlog question
3. only reopen Docker-related work if it is explicitly requested

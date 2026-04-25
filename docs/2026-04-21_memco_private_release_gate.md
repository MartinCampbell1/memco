# Memco Private Release Gate

Status note: checklist definition, not current checkout verdict.
Current verdict: see docs/CURRENT_STATUS.md.

## Phase 8 Private Gate

This document is the explicit Phase 8 gate checklist for the local private operator-controlled review-gated single-user release.

Date: 2026-04-21

## Scope

This document is the acceptance checklist for the local private operator-controlled review-gated single-user release.

It is intentionally not a strict original execution-brief gate.
It assumes the current Stage A owner-only actor exception.

Use it to answer:

- can one private owner/operator run the system end to end today?
- is the current local release honest about what it does and does not cover?

Fast repo-local status summary:

- [2026-04-22_memco_repo_local_status_snapshot.md](2026-04-22_memco_repo_local_status_snapshot.md)

Do not use it to claim:

- strict original execution-brief completion
- infra compliance with the PostgreSQL + Docker Compose + migration path
- actor-scoped multi-user contract completion
- universal memory substrate or fully autonomous production-memory readiness

## Checklist

| Gate item | Status | Evidence |
|---|---|---|
| Clean init | green | `tests/test_cli_smoke.py::test_cli_init_and_person_upsert` |
| Import JSON | green | `tests/test_cli_smoke.py::test_cli_operator_flow_supports_supersede_rollback` |
| Import plaintext | green | `tests/test_ingest_service.py::test_simple_file_import_writes_raw_and_db` |
| Person mapping | green | `tests/test_cli_smoke.py::test_cli_conversation_speaker_resolution` |
| Candidate extraction | green | `tests/test_cli_smoke.py::test_cli_candidate_extract_and_list` |
| Publish | green | `tests/test_cli_smoke.py::test_cli_operator_flow_supports_supersede_rollback` |
| Review resolution | green | `tests/test_cli_smoke.py::test_cli_review_flow_supports_latest_review_and_slug_resolution` |
| Retrieve | green | `tests/test_cli_smoke.py::test_cli_operator_flow_supports_supersede_rollback` |
| Refusal | green | `tests/test_cli_smoke.py::test_cli_operator_flow_supports_supersede_rollback` |
| Rollback | green | `tests/test_fact_lifecycle_rollback.py::test_rollback_reverts_superseded_current_state_fact` |
| Redacted retrieval logs | green | `tests/test_retrieval_logging.py::test_retrieval_logs_are_redacted` |
| Operator CLI flow from scratch | green | `tests/test_cli_smoke.py::test_cli_operator_flow_supports_latest_shortcuts` |

## Verification Commands

Run this private-release evidence set:

```bash
uv run pytest -q \
  tests/test_ingest_service.py \
  tests/test_cli_smoke.py \
  tests/test_retrieval_logging.py \
  tests/test_fact_lifecycle_rollback.py
```

Current recorded result:

- `31 passed in 1.73s`

## What This Gate Actually Proves

- the local runtime can bootstrap from a clean root
- an operator can create a person, import source material, convert source to conversation, extract candidates, resolve pending review items, publish facts, retrieve facts, and get refusal on unsupported claims
- rollback of a superseded current-state fact no longer leaves two active facts
- retrieval logs are redacted and do not store raw private query/fact text
- the current private eval artifact is still green (`24/24`) and now reports tracked token usage for the mock/deterministic path

## What This Gate Does Not Prove

- strict original execution-brief compliance
- broader multi-user actor/policy closure beyond the current API-scoped actor contract
- provider-agnostic LLM architecture
- token accounting
- acceptance-scale eval/reporting
- PostgreSQL + Docker Compose + migration-layer readiness

## Gate Interpretation

Private release readiness: evaluate against this checklist with fresh current checkout/config evidence.

Full brief readiness: not established by this gate.

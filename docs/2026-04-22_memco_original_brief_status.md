# Memco Strict Original Brief Status

Date: 2026-04-22
Status: reference-track status note

## Purpose

This document records the status of the original execution brief as a reference-track question.

It is not the active repo-local release gate.

For the active repo-local release surface, use:

- [2026-04-21_memco_release_readiness_gate.md](2026-04-21_memco_release_readiness_gate.md)

## Current Status

Current status: `NO-GO`

The repository is close on the non-Docker technical path, but it should not claim strict original-brief completion while Docker Compose remains an explicit requirement in the brief and is intentionally excluded from the chosen local workflow on this machine.

## Status By Area

| Area | Status | Why it blocks strict original-brief readiness |
|---|---|---|
| PostgreSQL runtime + migrations | green | Direct Postgres is live-proven, versioned migrations apply, and a reproducible no-Docker smoke path exists. |
| Docker Compose requirement from the brief | red | The repo still contains Docker artifacts, but Docker is intentionally not part of the chosen operating workflow on this machine. Until that brief requirement is explicitly waived or replaced, this remains a strict-brief gap. |
| Actor-scoped request contract | green | The user-facing API contract for `chat` / `retrieve` now requires actor context and enforces allowed person/domain scope. |
| Generic source layer | green | The code now has an explicit `source_documents` contract surface plus `source_segments`, and conversation messages are addressable as segment-level provenance. |
| Candidate lifecycle / publish gates | green | The lifecycle is strict, publish gates are enforced, and the current review path resolves both speaker ambiguity and the supported relation-target ambiguity path. |
| Provider-agnostic LLM adapter | green | A provider abstraction with `mock` and OpenAI-compatible adapters exists, and the OpenAI-compatible path is exercised through a local HTTP-compatible smoke test. |
| Token accounting | green | Token accounting is tracked for both deterministic/mock usage and the exercised OpenAI-compatible path. |
| Strict original-brief acceptance closure | red | Everything except the brief-level Docker Compose requirement is green, so strict original-brief closure remains open. |

## Checklist

| Strict original-brief gate item | Status | Note |
|---|---|---|
| Actor-scoped request contract | green | Required on the user-facing API and verified by tests. |
| Provider-agnostic LLM adapter | green | Present and verified across mock and OpenAI-compatible paths. |
| Token accounting | green | Tracked and verified for both deterministic and OpenAI-compatible paths. |
| Generic source layer | green | `source_documents` and `source_segments` are both explicit and wired in the current architecture. |
| PostgreSQL runtime + migrations | green | Live no-Docker Postgres proof, reproducible smoke, and migration application are all verified. |
| Docker Compose requirement from the brief | red | The chosen operator workflow on this machine intentionally avoids Docker, so strict brief closure still depends on either a spec change or an explicit decision to require Docker again. |
| Expanded eval artifact | green | Acceptance-style eval artifact is present and passing. |
| Implementation notes updated | green | Notes and release gates are current and explicit. |

## Verification Snapshot

```bash
test -f src/memco/migrations/postgres/0001_base.sql && echo "postgres migration present" || echo "postgres migration missing"
MEMCO_DATABASE_URL='postgresql://USER@127.0.0.1:5432/postgres' uv run memco postgres-smoke
uv run pytest -q tests/test_postgres_live_smoke.py
uv run pytest -q tests/test_api_actor_scope.py tests/test_api_chat.py tests/test_api_review.py tests/test_candidate_lifecycle_e2e.py tests/test_style_psychometric_guardrails.py
rg -n "actor_id|actor_type|allowed_person_ids|allowed_domains|can_view_sensitive" src/memco/models/retrieval.py src/memco/api/routes/chat.py src/memco/api/routes/retrieval.py || true
rg -n "source_segments|source_segment|source_documents" src docs
rg -n "provider-agnostic|tracked|token_accounting|mock provider|deterministic" src/memco/services/eval_service.py IMPLEMENTATION_NOTES.md
```

## Decision Rule

If the question is:

- `Can this repo honestly claim strict original execution-brief completion today?`
  - answer: `not strictly`, while Docker Compose remains an explicit brief requirement and the chosen local workflow intentionally avoids Docker

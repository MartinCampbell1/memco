# Memco Release Gap Remediation Plan

Date: 2026-04-21  
Source audit: `docs/2026-04-21_memco_grounded_audit.md`  
Baseline: `docs/synthius_mem_programmer_spec_v1_1_agent_ready.md`

Historical note:

- This was the original remediation plan captured before the later repo-local contract decisions.
- It is no longer the canonical implementation plan.
- Current canonical plan and contract docs:
  - [2026-04-21_memco_full_fix_plan.md](2026-04-21_memco_full_fix_plan.md)
  - [../synthius_mem_execution_brief.md](../synthius_mem_execution_brief.md)
  - [../2026-04-22_memco_contract_decision.md](../2026-04-22_memco_contract_decision.md)

## Triage summary

The repository is already a working private local prototype with a real memory loop, but it is not an honest `P0a done` implementation of the execution brief.

Validated gaps worth fixing:

- supersede rollback bug
- missing deviation documentation
- missing provider/token-accounting contract
- incomplete eval/reporting surface
- missing actor-scoped request contract, if the repo still claims full brief compliance

Validated non-goals for the next slice:

- do not widen into multi-user RBAC or public registration flows
- do not add UI/admin dashboard work
- do not attempt full full-spec implementation in one pass

## P0

### P0-1. Fix supersede rollback correctness

Why:

- This is the only currently reproduced product-integrity bug that can directly corrupt current-state truth for a single private user.

Files:

- `src/memco/repositories/fact_repository.py`
- `tests/test_fact_lifecycle_rollback.py`

Minimum sufficient edits:

- When rolling back a `superseded` operation, reactivate the old fact and demote or delete the newer successor fact referenced by `superseded_by_fact_id`.
- Clear reverse pointers consistently.
- Add a regression test that proves only one `active` current-state fact remains after rollback.

Verification:

- `uv run pytest -q tests/test_fact_lifecycle_rollback.py`
- `uv run pytest -q tests/test_retrieval_service.py`

### P0-2. Add explicit implementation deviation notes

Why:

- The repo currently presents itself closer to full completion than the implementation honestly supports.

Files:

- `IMPLEMENTATION_NOTES.md`
- `README.md`

Minimum sufficient edits:

- Create `IMPLEMENTATION_NOTES.md`.
- Record exact deviations:
  - SQLite instead of PostgreSQL/Docker
  - no provider-agnostic LLM adapter
  - simplified candidate lifecycle
  - 7-case smoke eval instead of acceptance-sized report
  - actor context not implemented
- Link the document from `README.md`.

Verification:

- `rg -n "SQLite instead of PostgreSQL|actor context|7-case smoke eval|candidate lifecycle" IMPLEMENTATION_NOTES.md README.md`

## P1

### P1-1. Decide the product contract: strict brief compliance or private-slice contract

Why:

- Several current gaps disappear if the repo is explicitly reframed as a private local slice rather than full `P0a`.

Files:

- `README.md`
- `docs/synthius_mem_programmer_spec_v1_1_agent_ready.md` or a new repo-local execution brief
- `IMPLEMENTATION_NOTES.md`

Minimum sufficient edits:

- Choose one path:
  - Path A: keep claiming `P0a` and implement the missing contract pieces.
  - Path B: explicitly reframe the repo as `private local vertical slice` and document deviations.
- Do not leave the repo in an ambiguous middle state.

Verification:

- Manual review of top-level docs for one consistent claim

### P1-2. Expand eval into a real acceptance artifact

Why:

- The current 7-case harness is useful but too small and missing required fields.

Files:

- `src/memco/services/eval_service.py`
- `src/memco/cli/main.py`
- `tests/test_eval_harness.py`

Minimum sufficient edits:

- Expand the fixture set toward the brief’s minimum coverage:
  - supported fact
  - unsupported premise
  - cross-person contamination
  - temporal update
  - duplicate merge
- Add report fields:
  - pass rate / accuracy
  - refusal correctness
  - evidence coverage
  - retrieval latency summary
  - token accounting placeholder or real counts once LLM adapter exists

Verification:

- `uv run pytest -q tests/test_eval_harness.py`
- `uv run memco eval-run --root /Users/martin/memco`

### P1-3. Add actor-scoped request models, or document the single-user exception

Why:

- This is a spec gap, but not necessarily a practical single-user blocker. It still needs a deliberate resolution.

Files:

- `src/memco/models/retrieval.py`
- `src/memco/api/routes/chat.py`
- `src/memco/api/routes/retrieval.py`
- `src/memco/api/deps.py`
- `tests/test_api_chat.py`

Minimum sufficient edits:

- Either:
  - implement `actor` on request payloads with simple dev assertions, or
  - explicitly document that the repo is single-user owner-only and does not implement actor scoping yet

Verification:

- `uv run pytest -q tests/test_api_chat.py`
- `uv run pytest -q tests/test_api_persons.py`

## P2

### P2-1. Add provider-agnostic LLM adapter and token accounting

Why:

- This is needed to honestly match the brief’s intended architecture, but it is not the first fix for single-user correctness.

Files:

- new `src/memco/llm/` package or equivalent
- `src/memco/config.py`
- `src/memco/services/extraction_service.py`
- `src/memco/services/retrieval_service.py`
- `src/memco/services/eval_service.py`
- tests for provider abstraction

Minimum sufficient edits:

- Add:
  - mock deterministic provider
  - OpenAI-compatible adapter interface
  - token counting/accounting surface
- Keep current deterministic extraction path as a fixture-compatible fallback if needed.

Verification:

- targeted provider tests
- eval output includes token accounting

### P2-2. Introduce generic source-segment abstraction

Why:

- This is structurally important for long-term correctness, but it does not currently block private chat ingestion.

Files:

- `src/memco/schema.sql`
- `src/memco/db.py`
- `src/memco/repositories/source_repository.py`
- `src/memco/repositories/conversation_repository.py`
- `src/memco/repositories/fact_repository.py`
- `src/memco/services/conversation_ingest_service.py`

Minimum sufficient edits:

- Add `source_documents` / `source_segments` equivalent tables.
- Make conversation messages addressable as source segments.
- Move evidence pointers to segment-level provenance.

Verification:

- ingestion tests
- evidence serialization tests
- retrieval still returns evidence correctly

## Do not do

- Do not start public-user auth, signup, billing, or profile systems.
- Do not add a dashboard or UI review queue before release-truthfulness is fixed.
- Do not replace the current working local prototype with a broad rewrite.
- Do not “solve” the infra mismatch by silently editing the spec without recording the deviation or consciously changing the product contract.

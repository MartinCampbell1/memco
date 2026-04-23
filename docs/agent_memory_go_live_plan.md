# Memco Agent Memory Go-Live Remediation Plan

Status: historical remediation plan, not current release verdict.
Current verdict lives in docs/2026-04-24_memco_release_closure.md and the active gate definition lives in docs/2026-04-21_memco_release_readiness_gate.md.
Keep this file as historical implementation context; do not use it as fresh GO proof without rerunning the current gates.

## Goal

Bring the current Memco checkout from "strict local quality gate passes" to "safe enough for real private agent-memory use" on a local operator setup.

This plan is based on the latest validation state:

- strict gate can pass
- the runtime no longer defaults to `mock`
- the extraction contract is now LLM-first
- but the live checkout is still not operationally ready because the current config is incomplete for a real provider and still runs on SQLite fallback instead of Postgres primary

---

## Current blockers

### Blocker 1 — Live runtime policy is not fail-closed enough

Current issue:

- `llm_runtime_policy()` treats `openai-compatible` as release-eligible even when `api_key` is empty
- the runtime looks healthy on paper, but an actual extraction call fails only at request time

Observed behavior:

- provider resolves to `OpenAICompatibleLLMProvider`
- first live completion call fails with `ValueError: MEMCO_LLM_API_KEY is required for the openai-compatible provider`

Why this matters:

- the current readiness gate can produce a false green result
- this is the single biggest reason the repo is still not operationally GO

### Blocker 2 — Canonical storage contract is not the actual live operator config

Current issue:

- the quality contract is Postgres-first
- the current `var/config/settings.yaml` still uses `storage.engine: sqlite`

Why this matters:

- there is now a validated Postgres path, but the real operator runtime is not actually using it
- that means the system is not yet running in the mode it claims as canonical

### Blocker 3 — Real live-provider proof is still missing in this checkout

Current issue:

- LLM-first extraction is proven by code and tests
- but there is no final proof that the exact repo-local config can ingest, extract, publish, retrieve, and answer using a real configured provider outside fixture mode

Why this matters:

- "contractually correct" is not the same as "operationally proven"

### Blocker 4 — Quality proof is still mostly synthetic

Current issue:

- benchmark scope is still `internal-approximation`
- benchmark disclaimer still says `synthetic benchmark; not paper-equivalent`
- token accounting is still partially incomplete for planner, retrieval, and answer

Why this matters:

- for real memory use, synthetic acceptance is helpful but not enough
- you need one thin but real operator-validation layer on top

### Blocker 5 — Operator safety needs one more hardening pass

Current issue:

- `api.auth_token` is still empty in the checked-in local config
- the system is intended for local/private use, but accidental exposure or weak local hygiene would still be risky

Why this matters:

- once real personal memory is stored, operational mistakes matter more than model quality mistakes

---

## Remediation principles

1. No more "green by contract wording only"
2. Readiness must be proven on the same runtime mode that will be used in practice
3. Postgres must become the actual primary live storage, not just the canonical validation path
4. A live provider must be configured and exercised end-to-end before GO
5. Roll out in stages: read-only first, write-back later

---

## Workstream A — Make runtime eligibility truly fail-closed

### Objective

A repo-local runtime must not be marked release-eligible unless it is actually callable.

### Files to change

- `src/memco/llm.py`
- `src/memco/release_check.py`
- `src/memco/api/routes/health.py`
- `tests/test_llm_provider.py`
- `tests/test_release_check.py`

### Required changes

1. Extend `llm_runtime_policy()` so it checks:
   - provider type
   - runtime profile
   - `api_key` presence for `openai-compatible`
   - non-empty `base_url`
2. Return explicit booleans such as:
   - `credentials_present`
   - `base_url_present`
   - `provider_configured`
   - `release_eligible`
3. Make `release_eligible = False` when:
   - provider is `mock`
   - runtime profile is `fixture`
   - API key is missing
   - provider config is incomplete
4. Add release-check assertions for incomplete provider config.
5. Expose these fields in `/health` so operator status is obvious.

### Acceptance criteria

- repo-local runtime with empty API key fails runtime policy gate
- strict release check fails before any misleading GO interpretation
- `/health` clearly shows why the runtime is not eligible

---

## Workstream B — Turn Postgres-first from contract into actual runtime truth

### Objective

The live operator config must run on Postgres primary by default.

### Files to change

- `var/config/settings.yaml`
- optionally `.env.example`
- `src/memco/config.py`
- `src/memco/release_check.py`
- `tests/test_release_check.py`

### Required changes

1. Change the local operator config from:
   - `storage.engine: sqlite`
   to:
   - `storage.engine: postgres`
2. Provide a real operator `MEMCO_DATABASE_URL`.
3. Keep SQLite only as:
   - fixture runtime
   - quick fallback path
   - emergency local dev mode
4. Ensure release reporting always distinguishes:
   - `primary`
   - `fallback`
5. Add one explicit check that the intended operator profile is not running on fallback storage during GO validation.

### Recommended operator config

Use environment variables for secrets and mutable deployment state:

```bash
export MEMCO_STORAGE_ENGINE=postgres
export MEMCO_DATABASE_URL='postgresql://memco:memco@127.0.0.1:5432/memco'
export MEMCO_LLM_PROVIDER='openai-compatible'
export MEMCO_LLM_BASE_URL='https://api.openai.com/v1'
export MEMCO_LLM_API_KEY='...'
export MEMCO_API_TOKEN='...'
```

### Acceptance criteria

- operator runtime resolves to Postgres primary
- `/health` shows `storage_role: primary`
- strict validation is run against the same storage mode that will be used in practice

---

## Workstream C — Add one real end-to-end live-provider smoke path

### Objective

Prove that the system works on a real provider outside fixture mode.

### Files to change

- `tests/` live smoke file or `scripts/` smoke runner
- `src/memco/release_check.py`
- possibly `src/memco/services/extraction_service.py`

### Required changes

1. Add one operator smoke path that runs only when env is present:
   - `MEMCO_RUN_LIVE_SMOKE=1`
   - valid API key
   - valid database URL
2. The smoke path should execute:
   - runtime bootstrap
   - ingest
   - extraction
   - candidate publish
   - retrieval
   - answer generation
3. Use a tiny gold sample with 2-3 people and 8-12 facts:
   - current residence
   - preference
   - employment
   - one temporal event
   - one unsupported premise
   - one subject-isolation case
4. Persist a compact artifact:
   - provider
   - storage engine
   - live smoke result
   - any failures

### Important rule

This smoke should be optional for CI, but mandatory before declaring real operator GO.

### Acceptance criteria

- a real configured provider returns structured extraction successfully
- the final answer includes `fact_ids` and `evidence_ids`
- unsupported and contradicted cases still refuse correctly

---

## Workstream D — Strengthen quality proof beyond synthetic benchmark only

### Objective

Keep the synthetic benchmark, but add one operator-focused validation layer.

### Files to change

- `src/memco/services/eval_service.py`
- `src/memco/release_check.py`
- `tests/test_eval_harness.py`
- new operator-golden-set fixture(s)

### Required changes

1. Keep the current synthetic/internal benchmark artifact.
2. Add a second thin evaluation set for operator readiness:
   - hand-authored
   - stable
   - small
   - focused on real failure modes
3. Minimum coverage for the operator set:
   - current fact retrieval
   - temporal "when" semantics
   - cross-person isolation
   - unsupported premise refusal
   - ambiguous/conflicting evidence
   - pending-review suppression
4. Report synthetic and operator-focused metrics separately.
5. Do not claim paper equivalence.

### Acceptance criteria

- release report distinguishes:
  - synthetic benchmark
  - operator readiness set
- operator set must be green before personal-data rollout

---

## Workstream E — Finish token accounting for planner, retrieval, answer

### Objective

Remove blind spots in usage visibility before real usage begins.

### Files to change

- `src/memco/services/planner_service.py`
- `src/memco/services/retrieval_service.py`
- `src/memco/services/answer_service.py`
- `src/memco/llm_usage.py`
- related tests

### Required changes

1. Instrument planner token usage.
2. Instrument answer token usage.
3. If retrieval stays deterministic, report that explicitly rather than `not_instrumented`.
4. Make benchmark output read like:
   - `measured_llm`
   - `deterministic`
   - `not_applicable`
   instead of ambiguous missing instrumentation.

### Acceptance criteria

- benchmark artifact no longer reports planner/retrieval/answer as unresolved blind spots
- operator can estimate cost and behavior per stage

---

## Workstream F — Operator security and safety hardening

### Objective

Do not start storing real personal memory without minimum local security hygiene.

### Files to change

- `var/config/settings.yaml`
- `.env.example`
- possibly API startup or health reporting

### Required changes

1. Set a non-empty API auth token.
2. Keep secrets out of checked-in config whenever possible.
3. Confirm actor-scope behavior before enabling automated writes.
4. Verify retrieval logs do not expose sensitive raw query text beyond intended policy.
5. Confirm backups for the Postgres database before real usage.

### Acceptance criteria

- operator auth token is configured
- provider credentials are injected via env or secure local secret storage
- Postgres backup path exists before real data import

---

## Recommended rollout sequence

### Phase 1 — Runtime integrity

1. Fix `llm_runtime_policy()` so missing credentials fail closed
2. switch live operator config to Postgres primary
3. set real secrets via env
4. verify `/health` reports:
   - release-eligible runtime
   - Postgres primary
   - credentials present

### Phase 2 — Operational proof

5. run strict Postgres release check
6. run one real live-provider end-to-end smoke
7. store the artifact from that run

### Phase 3 — Quality proof

8. add operator-focused readiness set
9. finish token instrumentation
10. rerun strict gate plus operator-live smoke

### Phase 4 — Safe rollout

11. enable Memco in read-only retrieval mode for agents
12. keep fact publication behind review
13. only later consider semi-automated write-back

---

## Safe rollout policy

### Stage 1 — Allowed

- ingest real data
- retrieve facts
- answer questions
- keep candidate publication reviewed

### Stage 2 — Allowed after manual verification

- agent-assisted candidate creation
- human-approved publish flow

### Stage 3 — Not recommended yet

- fully automated write-back into memory with no review layer

---

## Definition of Done

Memco is GO for real private agent-memory use only when all items below are true at the same time:

1. `llm_runtime_policy()` fails closed on missing credentials.
2. The live operator config uses a real provider with valid credentials.
3. The live operator config runs on Postgres primary.
4. Strict release check passes on the same practical runtime mode.
5. A real live-provider end-to-end smoke passes outside fixture mode.
6. Operator-focused readiness cases pass.
7. Token accounting blind spots are closed or explicitly classified.
8. API auth token and secret handling are configured.
9. Initial rollout is read-only or review-gated.

---

## Minimal command checklist before GO

```bash
export MEMCO_STORAGE_ENGINE=postgres
export MEMCO_DATABASE_URL='postgresql://memco:memco@127.0.0.1:5432/memco'
export MEMCO_LLM_PROVIDER='openai-compatible'
export MEMCO_LLM_BASE_URL='https://api.openai.com/v1'
export MEMCO_LLM_API_KEY='...'
export MEMCO_API_TOKEN='...'
```

Run tests:

```bash
/Users/martin/memco/.venv/bin/python -m pytest -q
```

Run strict gate:

```bash
env PYTHONPATH=/Users/martin/memco/src /Users/martin/memco/.venv/bin/python - <<'PY'
from pathlib import Path
from memco.release_check import run_strict_release_check

result = run_strict_release_check(
    project_root=Path('/Users/martin/memco'),
    postgres_database_url='postgresql://memco:memco@127.0.0.1:5432/memco',
)
print(result['ok'])
for step in result['steps']:
    print(step['name'], step.get('ok'), step.get('reason', ''))
PY
```

Then run one real live smoke before enabling agents against the system.

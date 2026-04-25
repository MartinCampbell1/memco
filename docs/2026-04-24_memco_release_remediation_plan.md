Historical document. Not current verdict.
Current verdict: see docs/CURRENT_STATUS.md

# Memco Release Remediation Plan

Date: 2026-04-24
Status: historical pre-remediation plan, not current release verdict.
Current verdict: see `docs/CURRENT_STATUS.md`.
Audit package index: `docs/2026-04-24_memco_audit_package_index.md`
Source audit: `docs/2026-04-24_memco_final_release_audit.md`
Russian executive summary: `docs/2026-04-24_memco_final_release_audit_ru.md`
Contract compliance matrix: `docs/2026-04-24_memco_contract_compliance_matrix.md`
Evidence appendix: `docs/2026-04-24_memco_audit_evidence_appendix.md`
Blocker ticket pack: `docs/2026-04-24_memco_blocker_ticket_pack.md`
Docs status map: `docs/2026-04-24_memco_docs_status_map.md`
Scope: fix only the blockers required for honest private owner/operator GO.

## Goal

This plan records the staged remediation path that was needed after the pre-remediation audit. For the current checkout status, use `docs/CURRENT_STATUS.md` instead of treating this file as an active verdict.

Bring the current Memco checkout from:

```text
core private memory loop works, but final release gate is red
```

to:

```text
local private operator-controlled Hermes/API-backed memory is honestly GO
```

This plan does not target public SaaS readiness, registration, billing, organization profiles, or full original-brief Docker Compose completion.

## Next Programmer-Agent Kickoff

Use this prompt for the next implementation pass:

```text
You are working in /Users/martin/memco.

Do not restart the audit. Read these files first:
- docs/2026-04-24_memco_audit_package_index.md
- docs/2026-04-24_memco_final_release_audit.md
- docs/2026-04-24_memco_final_release_audit_ru.md
- docs/2026-04-24_memco_contract_compliance_matrix.md
- docs/2026-04-24_memco_audit_evidence_appendix.md
- docs/2026-04-24_memco_release_remediation_plan.md
- docs/2026-04-24_memco_blocker_ticket_pack.md
- docs/2026-04-24_memco_docs_status_map.md

Goal: make the current local/private/operator-controlled/review-gated Memco checkout honestly GO for Martin's single-user Hermes/API-backed use.

Do not implement public SaaS registration, billing, profiles, org/team management, or broad multi-user UX.

Fix only the release blockers:
1. root IMPLEMENTATION_NOTES.md path mismatch / docs-contract failures
2. unstable API actor credentials for Hermes/API use
3. incomplete HTTP docs/examples for routes requiring actor
4. stale/historical docs that contradict current release state
5. fresh release-grade proof for the current checkout

Do not weaken gates. Do not count fixture/mock paths as live release proof. Do not put real provider keys in git. Do not claim GO until uv run pytest -q is green and release-readiness-check passes with live smoke and fresh artifact semantics.
```

## Non-Negotiable Rules

1. Do not commit real provider keys.
2. Do not make empty or fake keys count as release-eligible.
3. Do not claim old `var/reports/*current*` artifacts as fresh proof after changing the checkout.
4. Do not weaken `runtime_policy`, `operator_safety`, `storage_contract`, `benchmark`, or `live_operator_smoke` just to make gates green.
5. Do not call quick `release-check` or `strict-release-check` a final release claim unless `release-readiness-check` also passes with live smoke.
6. Do not reopen public SaaS auth/profile work unless explicitly requested.

## Stage 0 - Freeze Current Evidence

Purpose: preserve the audit baseline before remediation starts.

Actions:

1. Read `docs/2026-04-24_memco_final_release_audit.md`.
2. Capture current git state.
3. Confirm the known red gates are still red before changing code.

Commands:

```bash
cd /Users/martin/memco
git status --short --branch
uv run pytest -q
uv run memco release-check --project-root /Users/martin/memco --output /tmp/memco-before-fix-release-check.json || true
uv run memco operator-preflight --project-root /Users/martin/memco || true
```

Expected proof:

- full suite still fails on docs contract before fixes
- release-check still fails closed without live provider env
- operator-preflight still reports missing live LLM credentials in a plain shell

Do not proceed if the baseline differs without explaining why.

## Stage 1 - Repair The Docs Contract Path Break

Blocker: root `IMPLEMENTATION_NOTES.md` is deleted, but docs/tests still expect it.

Recommended decision:

Keep `IMPLEMENTATION_NOTES.md` at repo root unless there is a strong reason to move it. The original strict brief explicitly names that root file, and existing tests already guard it.

Files likely involved:

- `IMPLEMENTATION_NOTES.md`
- `docs/IMPLEMENTATION_NOTES.md`
- `README.md`
- `docs/2026-04-21_memco_release_readiness_gate.md`
- `tests/test_docs_contract.py`

Minimum acceptable fixes:

Option A:

- restore root `IMPLEMENTATION_NOTES.md`
- remove or ignore the duplicate `docs/IMPLEMENTATION_NOTES.md`
- keep current tests mostly unchanged

Option B:

- intentionally move the canonical file into `docs/`
- update every link and every docs-contract test
- update original-brief/deviation wording so the move is explicit

Preferred: Option A, because it is smaller and aligns with the original brief wording.

Verification:

```bash
uv run pytest -q tests/test_docs_contract.py
uv run pytest -q
```

Done when:

- docs contract test is green
- full suite no longer fails because of missing implementation notes

## Stage 2 - Stabilize API Actor Credentials For Hermes/API Use

Blocker: actor policies are generated randomly when missing from local config, but API routes require actor credentials.

Current failure:

```text
no actor -> 422 Actor context is required
actor from previous settings load -> 403 Invalid actor credentials
```

Why this blocks the real user flow:

The intended usage is seed once, then connect Hermes/API. Hermes cannot reliably call actor-scoped endpoints if valid actor payloads are not stable across process/config loads.

Files likely involved:

- `src/memco/config.py`
- `src/memco/runtime.py`
- `src/memco/cli/main.py`
- `src/memco/operator_preflight.py`
- `tests/test_config.py`
- `tests/test_api_actor_scope.py`
- `tests/test_operator_preflight.py`
- `README.md`

Recommended design:

1. Keep actor credentials out of tracked files.
2. Persist generated actor policies into local ignored runtime config under `var/config/settings.yaml`.
3. Backfill missing `api.actor_policies` in existing local configs during a safe runtime/config initialization path.
4. Provide an operator-visible command or preflight output that prints the actor ids and explains how to build the actor block without exposing secrets in tracked docs.
5. Preserve the API requirement that `/v1/retrieve`, `/v1/chat`, and `/v1/ingest/pipeline` require actor context.

Required tests:

1. Fresh runtime writes stable actor policies.
2. Existing config missing `api.actor_policies` is backfilled once and then remains stable.
3. Actor payload built from one settings load is accepted after a separate settings load.
4. Forged actor is still rejected.
5. `operator-preflight` detects whether stable actor policies are available for the intended operator path.

Suggested focused command:

```bash
uv run pytest -q \
  tests/test_config.py \
  tests/test_api_actor_scope.py \
  tests/test_api_ingest_conversation.py \
  tests/test_operator_preflight.py
```

Done when:

- actor credentials are stable for the local ignored runtime config
- a documented actor payload can be used by an external Hermes/API caller
- forged or stale actors are still rejected

## Stage 3 - Fix HTTP Seed/API Documentation

Blocker: README `/v1/ingest/pipeline` examples omit `actor`, but the route requires actor.

Files likely involved:

- `README.md`
- `docs/2026-04-21_memco_release_readiness_gate.md`
- `docs/2026-04-22_memco_repo_local_status_snapshot.md`
- `tests/test_docs_contract.py`

Required updates:

1. Add API token header to HTTP examples.
2. Add actor block to `/v1/ingest/pipeline`, `/v1/retrieve`, and `/v1/chat` examples where applicable.
3. Explain that CLI/local owner mode is the Stage A exception, not the public API contract.
4. Add docs-contract assertions that the examples mention actor context.

Example shape:

```json
"actor": {
  "actor_id": "dev-owner",
  "actor_type": "owner",
  "auth_token": "from local ignored runtime config",
  "allowed_person_ids": [],
  "allowed_domains": [],
  "can_view_sensitive": true
}
```

Verification:

```bash
uv run pytest -q tests/test_docs_contract.py tests/test_api_ingest_conversation.py tests/test_api_actor_scope.py
```

Done when:

- README examples no longer fail as written because of missing actor context
- docs explicitly distinguish CLI owner exception from API actor requirement

## Stage 4 - Mark Stale Plans As Historical

Blocker: several docs are useful history but misleading if read as current state.

Files to classify:

- `docs/agent_memory_go_live_plan.md`
- `docs/programmer_agent_no_shortcuts_release_plan.md`
- `dorabotka.md`
- any old plan that says mock/live/Postgres blockers still exist after they were remediated

Required updates:

1. Add a clear header to each historical plan:

```text
Status: historical remediation plan, not current release verdict.
Current verdict: see docs/CURRENT_STATUS.md. The active gate definition lives in docs/2026-04-21_memco_release_readiness_gate.md.
```

2. Do not rewrite history. Keep old evidence, but stop it from looking current.
3. Ensure README points to the active contract docs first.

Verification:

```bash
uv run pytest -q tests/test_docs_contract.py
rg -n "not operationally ready|mock|SQLite fallback|not mandatory|hard blockers" docs dorabotka.md README.md
```

Done when:

- stale plan docs cannot reasonably be mistaken for the current release verdict

## Stage 5 - Rebuild Fresh Release Proof

Purpose: produce current, non-stale release evidence after fixes.

Prerequisites:

- full suite green
- stable actor policy path landed
- README/API examples fixed
- live provider env available in the operator shell
- local Postgres reachable

Plain-shell fail-closed proof:

```bash
env -u MEMCO_LLM_PROVIDER \
    -u MEMCO_LLM_MODEL \
    -u MEMCO_LLM_BASE_URL \
    -u MEMCO_LLM_API_KEY \
    -u MEMCO_RUN_LIVE_SMOKE \
  uv run memco release-check \
    --project-root /Users/martin/memco \
    --output /tmp/memco-plain-release-check.json || true
```

Expected:

```text
ok: false
runtime_policy.reason: openai-compatible provider is missing api_key
```

Operator preflight with live provider:

```bash
MEMCO_LLM_PROVIDER='openai-compatible' \
MEMCO_LLM_MODEL='gpt-5.4-mini' \
MEMCO_LLM_BASE_URL='http://127.0.0.1:2455/v1' \
MEMCO_LLM_API_KEY='from-local-secret-store' \
MEMCO_API_TOKEN='from-local-secret-store' \
MEMCO_POSTGRES_DATABASE_URL='postgresql://martin@127.0.0.1:5432/postgres' \
scripts/operator_preflight.sh
```

Expected:

```text
operator_preflight ok: true
```

Release-grade proof:

```bash
MEMCO_RUN_LIVE_SMOKE=1 \
MEMCO_LLM_PROVIDER='openai-compatible' \
MEMCO_LLM_MODEL='gpt-5.4-mini' \
MEMCO_LLM_BASE_URL='http://127.0.0.1:2455/v1' \
MEMCO_LLM_API_KEY='from-local-secret-store' \
MEMCO_API_TOKEN='from-local-secret-store' \
uv run memco release-readiness-check \
  --project-root /Users/martin/memco \
  --postgres-database-url 'postgresql://martin@127.0.0.1:5432/postgres' \
  --output /Users/martin/memco/var/reports/release-readiness-check-current.json
```

Expected:

```text
ok: true
gate_type: release-grade
live_smoke_required: true
live_smoke_requested: true
live_operator_smoke ok: true
```

Artifact refresh:

```bash
uv run memco local-artifacts-refresh \
  --project-root /Users/martin/memco \
  --postgres-database-url 'postgresql://martin@127.0.0.1:5432/postgres' \
  --output /Users/martin/memco/var/reports/local-artifacts-refresh-postgres-current.json
```

Freshness check:

```bash
uv run python - <<'PY'
import json
from pathlib import Path
from memco.artifact_semantics import evaluate_artifact_freshness

root = Path('/Users/martin/memco')
for name in [
    'release-check-current.json',
    'release-check-postgres-current.json',
    'strict-release-check-current.json',
    'release-readiness-check-current.json',
    'live-operator-smoke-current.json',
    'repo-local-status-current.json',
]:
    path = root / 'var' / 'reports' / name
    payload = json.loads(path.read_text())
    print(name, evaluate_artifact_freshness(payload, project_root=root))
PY
```

Done when:

- all final artifacts are current for checkout/config
- release-readiness-check is green with live smoke
- plain-shell fail-closed behavior remains red without credentials

## Stage 6 - Final Auditor Recheck

Run the final audit commands again after remediation:

```bash
git status --short --branch
uv run pytest -q
uv run pytest -q \
  tests/test_docs_contract.py \
  tests/test_release_check.py \
  tests/test_cli_release_check.py \
  tests/test_config.py \
  tests/test_llm_provider.py \
  tests/test_operator_preflight.py \
  tests/test_api_actor_scope.py \
  tests/test_api_ingest_conversation.py
uv run memco eval-run --root "$(mktemp -d)"
```

Then rerun:

```bash
uv run memco release-readiness-check \
  --project-root /Users/martin/memco \
  --postgres-database-url 'postgresql://martin@127.0.0.1:5432/postgres'
```

with live env and `MEMCO_RUN_LIVE_SMOKE=1`.

Final GO requires all of:

- full suite green
- docs-contract green
- plain-shell release-check fails closed without live creds
- operator preflight green with live creds
- release-readiness-check green with live smoke
- current artifacts not stale
- no README/API example contradicts route requirements
- Hermes/API actor credentials stable across settings loads/processes

## What Not To Fix In This Pass

Do not spend this pass on:

- public registration/profile UX
- billing
- organization/team ACLs
- public SaaS hardening
- Docker Compose as day-to-day runtime
- WhatsApp/Telegram parsers
- admin dashboard
- major architecture rewrite

Those are either explicitly out of the private single-user scope or belong to a separate strict-original/full-product track.

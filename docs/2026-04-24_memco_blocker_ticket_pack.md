# Memco Blocker Ticket Pack

Date: 2026-04-24
Status: historical pre-remediation ticket pack, not current release verdict.
Current release verdict lives in `docs/2026-04-24_memco_release_closure.md`.
Audit package index: `docs/2026-04-24_memco_audit_package_index.md`
Source audit: `docs/2026-04-24_memco_final_release_audit.md`
Evidence appendix: `docs/2026-04-24_memco_audit_evidence_appendix.md`
Remediation plan: `docs/2026-04-24_memco_release_remediation_plan.md`
Docs status map: `docs/2026-04-24_memco_docs_status_map.md`

## Purpose

This file converts the final audit into implementation tickets.

These tickets describe the pre-remediation blocker queue. The current private release closure records which blockers were remediated and what fresh evidence supports the present `GO`.

These tickets are intentionally scoped to Martin's current private, single-user, Hermes/API-backed use case. They do not ask for public SaaS accounts, billing, public profiles, or broad multi-user UX.

## Ticket 0 - Preserve Baseline Before Fixes

Priority: P0
Type: audit-control

### Problem

The current checkout is dirty and has red gates. A programmer-agent must not accidentally treat old green artifacts as current proof.

### Required work

1. Read the audit package before coding.
2. Capture current `git status --short --branch`.
3. Reproduce the current red gates before making fixes.

### Commands

```bash
cd /Users/martin/memco
git status --short --branch
uv run pytest -q || true
uv run memco release-check --project-root /Users/martin/memco --output /tmp/memco-before-fix-release-check.json || true
uv run memco operator-preflight --project-root /Users/martin/memco || true
```

### Acceptance criteria

- The agent records whether the baseline still matches the audit.
- If the baseline differs, the agent explains why before changing code.
- No old `var/reports/*current*` artifact is used as current GO proof without freshness validation.

### Non-goals

- Do not fix code in this ticket.
- Do not stage or commit audit artifacts unless explicitly asked.

## Ticket 1 - Restore Or Complete `IMPLEMENTATION_NOTES.md` Path Decision

Priority: P0
Type: docs/tests contract

### Problem

The current full suite fails because root `IMPLEMENTATION_NOTES.md` is deleted while docs and tests still expect it. There is an untracked `docs/IMPLEMENTATION_NOTES.md`, but the move is incomplete.

### Evidence

```text
uv run pytest -q -> 2 failed, 345 passed
tests/test_docs_contract.py::test_implementation_notes_use_original_brief_language
tests/test_docs_contract.py::test_current_contract_explicitly_scopes_out_whatsapp_and_telegram
```

Known references to the root file:

```text
README.md
docs/synthius_mem_execution_brief.md
docs/2026-04-21_memco_release_readiness_gate.md
tests/test_docs_contract.py
```

### Required work

Choose exactly one canonical path:

Option A, preferred:

- restore root `IMPLEMENTATION_NOTES.md`
- remove or ignore the duplicate `docs/IMPLEMENTATION_NOTES.md`
- keep existing docs/tests mostly unchanged

Option B:

- intentionally move canonical notes to `docs/IMPLEMENTATION_NOTES.md`
- update every doc link and docs-contract test
- explicitly document the deviation from the original brief naming

### Acceptance criteria

- `uv run pytest -q tests/test_docs_contract.py` passes.
- `uv run pytest -q` passes or only fails on unrelated, newly documented issues.
- There is exactly one canonical implementation notes location.
- The strict original-brief status and active repo-local docs agree with that location.

### Non-goals

- Do not weaken docs-contract tests to hide the missing file.
- Do not remove implementation-notes requirements from the audit trail.

## Ticket 2 - Stabilize API Actor Credentials For Hermes/API

Priority: P0
Type: runtime/API auth

### Problem

The current root config does not persist `api.actor_policies`. Defaults are generated using random tokens. A caller can build an actor from one settings load and receive `403 Invalid actor credentials` when the API route loads settings again.

### Evidence

```text
raw_config_has_api_actor_policies False
tokens_stable_between_loads {'dev-owner': False, 'eval-runner': False, 'maintenance-admin': False, 'system': False}
prior_load_actor_status 403 Invalid actor credentials for /v1/retrieve.
```

Relevant code:

```text
src/memco/config.py
src/memco/api/deps.py
src/memco/api/routes/retrieval.py
src/memco/api/routes/chat.py
src/memco/api/routes/ingest.py
```

### Required work

Implement a local/private actor credential strategy that is stable across settings loads and processes.

Recommended shape:

1. Keep real actor tokens out of tracked files.
2. Persist generated actor policies into the local ignored runtime config, or load them from an ignored local secret file.
3. Backfill missing local `api.actor_policies` safely.
4. Provide an operator-visible way to inspect or generate the actor block needed by Hermes.
5. Ensure TestClient/API route behavior uses the same stable credentials as external callers.

### Acceptance criteria

- Two separate `load_settings('/Users/martin/memco')` calls produce the same actor tokens for persisted actors.
- A retrieve/chat/ingest request using an actor built before route execution is accepted when otherwise valid.
- Forged actor tests still fail.
- Admin/eval/owner permission boundaries still pass.
- No real actor token is committed to tracked source/docs.

### Suggested tests

```bash
uv run pytest -q tests/test_api_actor_scope.py tests/test_api_chat.py tests/test_api_ingest_conversation.py tests/test_config.py
```

Add or update tests for:

- stable actor policies across separate settings loads
- missing-policy backfill behavior
- no accidental fallback to random tokens when a runtime config already exists

### Non-goals

- Do not add public user registration.
- Do not add profile management UI.
- Do not disable actor requirements on user-facing API routes.

## Ticket 3 - Fix HTTP API Documentation For Required Actor Context

Priority: P1
Type: operator docs/API examples

### Problem

README HTTP examples for `/v1/ingest/pipeline` omit `actor`, but the route requires actor context.

### Evidence

```text
src/memco/api/routes/ingest.py route_label="/v1/ingest/pipeline", require_actor=True
README.md curl examples omit actor
```

### Required work

1. Update README HTTP examples to include:
   - API auth token header
   - actor block
   - where the operator gets the actor block/token
2. Align examples for:
   - `/v1/ingest/pipeline`
   - `/v1/retrieve`
   - `/v1/chat`
3. Make private CLI exception clear:
   - CLI/local owner mode can omit API actor payload
   - HTTP API routes require actor context

### Acceptance criteria

- Copy-pasted examples are structurally valid for the current API.
- Docs-contract tests verify HTTP examples mention actor.
- No doc claims public SaaS onboarding is required.

### Non-goals

- Do not make the HTTP API anonymous.
- Do not remove actor context from routes to make old examples work.

## Ticket 4 - Mark Historical/Stale Plans And Status Docs

Priority: P1
Type: docs release honesty

### Problem

The docs tree contains historical/remediation files and older green claims that can be misread as current release state. Current audit evidence says release-grade gates are red for this dirty checkout.

### Required work

Add clear status headers to stale/historical docs, or move them under a historical/plans path if appropriate.

At minimum review:

```text
docs/agent_memory_go_live_plan.md
docs/programmer_agent_no_shortcuts_release_plan.md
dorabotka.md
docs/2026-04-21_memco_release_readiness_gate.md
docs/2026-04-22_memco_repo_local_status_snapshot.md
docs/2026-04-22_memco_original_brief_status.md
```

### Acceptance criteria

- A future agent can tell which document is active current contract vs historical plan vs stale snapshot.
- Any `GO` claim is tied to a fresh artifact or clearly marked historical.
- Strict original brief remains separate from active repo-local private release scope.

### Non-goals

- Do not delete useful historical evidence.
- Do not rewrite history to hide previous NO-GO or GO claims.

## Ticket 5 - Rebuild Fresh Release Proof

Priority: P0
Type: release validation

### Problem

Existing green artifacts are stale relative to the current dirty checkout. The current `release-readiness-check` is red.

### Required work

After Tickets 1-4, rerun release validation from the current checkout.

### Commands

```bash
cd /Users/martin/memco
uv run pytest -q
uv run memco operator-preflight --project-root /Users/martin/memco
MEMCO_RUN_LIVE_SMOKE=1 \
MEMCO_API_TOKEN='...' \
MEMCO_LLM_API_KEY='...' \
uv run memco release-readiness-check \
  --project-root /Users/martin/memco \
  --postgres-database-url 'postgresql://martin@127.0.0.1:5432/postgres' \
  --output /Users/martin/memco/var/reports/release-readiness-check-current.json
```

Then validate freshness:

```bash
uv run python - <<'PY'
import json
from pathlib import Path
from memco.artifact_semantics import evaluate_artifact_freshness

root = Path('/Users/martin/memco')
path = root / 'var' / 'reports' / 'release-readiness-check-current.json'
payload = json.loads(path.read_text())
print(evaluate_artifact_freshness(payload, project_root=root))
PY
```

### Acceptance criteria

- `uv run pytest -q` is green.
- `operator-preflight` is green with live provider env.
- `release-readiness-check` returns `ok=true`.
- live operator smoke ran and passed.
- artifact freshness reports `current_for_checkout_config=True`.
- The release artifact records the current git head, dirty context, runtime mode, config source, and live-smoke state.

### Non-goals

- Do not count fixture-only eval as release proof.
- Do not count quick `release-check` as final release proof unless release-readiness is also green.
- Do not fake provider credentials.

## Ticket 6 - Final Auditor Recheck

Priority: P0
Type: independent verification

### Problem

The project should not move from NO-GO to GO based only on the implementing agent's own statement.

### Required work

Run an independent audit after fixes.

### Acceptance criteria

The final auditor can reproduce:

```text
full suite green
actor credentials stable
HTTP examples runnable in shape
operator-preflight green with live provider env
release-readiness-check ok=true with live smoke
artifact freshness current_for_checkout_config=True
old stale docs clearly marked
```

### Non-goals

- Do not expand to public SaaS scope during final recheck.
- Do not require Docker Compose unless Martin explicitly changes the accepted local workflow.

# Memco Final Release Audit

Date: 2026-04-24
Auditor: Codex
Scope: current working tree at `/Users/martin/memco`
Status: historical pre-remediation audit baseline, not current release verdict.
Current release verdict lives in `docs/2026-04-24_memco_release_closure.md`.

Related follow-up artifacts:

- audit package index: `docs/2026-04-24_memco_audit_package_index.md`
- Russian executive summary: `docs/2026-04-24_memco_final_release_audit_ru.md`
- contract compliance matrix: `docs/2026-04-24_memco_contract_compliance_matrix.md`
- evidence appendix: `docs/2026-04-24_memco_audit_evidence_appendix.md`
- remediation plan: `docs/2026-04-24_memco_release_remediation_plan.md`
- blocker ticket pack: `docs/2026-04-24_memco_blocker_ticket_pack.md`
- docs status map: `docs/2026-04-24_memco_docs_status_map.md`

## Final Verdict

Final gate: **NO-GO for real private Hermes/API-backed agent-memory use today**.

This is not a verdict that Memco is fake or empty. The core private memory loop is real and materially implemented. The issue is narrower and more important: the current checkout does not satisfy the repository's own final release criteria, and the API/Hermes integration path has a concrete credential-stability blocker.

Short answer to the owner/operator question:

- **Can one technical owner test and use the core memory loop locally through CLI/dev flows?** Yes, cautiously.
- **Can this checkout honestly be called fully release-ready for the owner's real private agent-memory use through Hermes/API?** No.
- **Does it fully satisfy the original execution brief as written?** No.
- **Are missing public profiles, registration, billing, or SaaS multi-user UX blockers for the owner's private use?** No.

## Contracts Checked

### Original strict brief

Original/reference documents:

- `docs/synthius_mem_programmer_spec_v1_1_agent_ready.md`
- `docs/synthius_mem_programmer_spec.md`

Strict original P0a includes:

- JSON/plaintext conversation ingestion
- speaker/person resolution
- token-bounded chunking
- extraction for core domains
- validation and candidate lifecycle
- consolidation into active memory
- evidence-backed retrieval
- refusal on unsupported premise
- minimal chat endpoint plus CLI
- small golden eval report
- PostgreSQL through Docker Compose plus migration layer
- actor/viewer request context
- `IMPLEMENTATION_NOTES.md` listing deviations

Current strict original status remains **NO-GO**, consistent with `docs/2026-04-22_memco_original_brief_status.md`. The main intentional mismatch is Docker Compose: the repo-local contract accepts no-Docker Postgres on this machine, but the original brief still names Docker Compose explicitly.

### Active repo-local contract

Active/current documents:

- `docs/synthius_mem_execution_brief.md`
- `docs/2026-04-22_memco_contract_decision.md`
- `docs/2026-04-21_memco_release_readiness_gate.md`
- `docs/2026-04-21_memco_private_release_gate.md`
- `docs/2026-04-22_memco_repo_local_status_snapshot.md`

The accepted repo-local contract is a local/private/operator-controlled/review-gated single-user slice, with a separate reference track for strict original-brief completion.

This narrowing is valid for Martin's stated use. Public registration, profile systems, public SaaS auth, billing, organization ACLs, and broad multi-user UI are not required for the private single-user product.

However, the narrowed contract still requires full operational proof before final release claims:

- canonical Postgres path
- operator-readiness
- live provider readiness
- live operator smoke
- current, fresh release artifacts
- passing tests
- honest docs

## Validation Run In This Audit

Commands were run against the current working tree, not just old artifacts.

### Git/worktree

Observed:

```text
## main...origin/main
33 dirty entries before this audit report was added
```

The tree contains tracked modifications/deletions plus untracked release-plan/operator files. This matters because `var/reports/*current*` artifacts were generated against an older dirty status hash. After this report was added, the working tree has one additional untracked audit file.

### Full test suite

Command:

```bash
uv run pytest -q
```

Result:

```text
2 failed, 345 passed
```

Failures:

- `tests/test_docs_contract.py::test_implementation_notes_use_original_brief_language`
- `tests/test_docs_contract.py::test_current_contract_explicitly_scopes_out_whatsapp_and_telegram`

Root cause:

- root `IMPLEMENTATION_NOTES.md` is deleted
- `docs/IMPLEMENTATION_NOTES.md` exists as an untracked file
- tests still read `IMPLEMENTATION_NOTES.md` from repo root
- README and release docs still link the old root path

This is a release blocker because the repo deliberately uses docs-contract tests to prevent readiness wording drift.

### Private core-loop subset

Command:

```bash
uv run pytest -q \
  tests/test_ingest_service.py \
  tests/test_cli_smoke.py \
  tests/test_retrieval_logging.py \
  tests/test_fact_lifecycle_rollback.py
```

Result:

```text
38 passed
```

Interpretation:

The local private memory loop is substantially real: import, candidate flow, retrieval, refusal, logging, and rollback have passing coverage.

### Eval harness

Command:

```bash
tmpdir=$(mktemp -d)
uv run memco eval-run --root "$tmpdir"
```

Result:

```text
27/27 passed
pass_rate = 1.0
```

Interpretation:

The internal/private acceptance harness is green. This is useful regression evidence, but it is not a final release-grade proof by itself because it runs in fixture/eval mode and does not prove the current operator runtime with live credentials.

### Quick repo-local release check

Command:

```bash
uv run memco release-check \
  --project-root /Users/martin/memco \
  --output /tmp/memco-audit-release-check.json
```

Result:

```text
ok: false
runtime_policy.reason: openai-compatible provider is missing api_key
pytest_gate: 2 failed, 50 passed
acceptance_artifact: skipped because pytest_gate_failed
```

Interpretation:

The fail-closed runtime policy is working correctly, but the current checkout is not green. A release claim would need live provider env injection and a fixed docs contract.

### Release-grade readiness check

Command:

```bash
uv run memco release-readiness-check \
  --project-root /Users/martin/memco \
  --postgres-database-url 'postgresql://martin@127.0.0.1:5432/postgres' \
  --output /tmp/memco-audit-release-readiness.json
```

Result:

```text
ok: false
runtime_policy: false
pytest_gate: false
postgres_smoke: skipped because prior_gate_failed
benchmark_artifact: skipped because prior_gate_failed
live_operator_smoke: required, skipped, live_smoke_required_for_release_claim
```

Interpretation:

The actual final gate is red in the current shell.

### Operator preflight

Command:

```bash
uv run memco operator-preflight --project-root /Users/martin/memco
```

Result:

```text
ok: false
runtime_policy: openai-compatible provider is missing api_key
operator_env: missing live_llm_credentials
db_reachability: ok
backup_path: ok
provider_reachability: skipped because runtime_policy_failed
```

Interpretation:

Postgres path and backup path are present, but the live operator runtime is not release-eligible without provider credentials.

## Release Gaps

### P0-1. Current checkout does not pass tests

Severity: release blocker

Evidence:

- full suite: `2 failed, 345 passed`
- docs-contract test reads deleted root `IMPLEMENTATION_NOTES.md`

Why it matters:

The repo explicitly relies on docs-contract tests to stop false readiness claims. A green release claim while this test is red would violate the active release process.

Minimum remediation:

- either restore root `IMPLEMENTATION_NOTES.md`
- or update README/release docs/tests to consistently use `docs/IMPLEMENTATION_NOTES.md`
- rerun full suite

### P0-2. Current release-grade gate is red

Severity: release blocker

Evidence:

- `release-check --project-root /Users/martin/memco`: `ok: false`
- `release-readiness-check --project-root /Users/martin/memco --postgres-database-url ...`: `ok: false`

Why it matters:

The active execution brief requires release-grade proof through canonical Postgres, operator-readiness, and live operator smoke before final release claims. The current shell does not provide that proof.

Minimum remediation:

- inject valid live provider env
- use supported model/provider settings
- run operator preflight
- run release-readiness-check with `MEMCO_RUN_LIVE_SMOKE=1`
- regenerate current artifacts

### P0-3. Existing green artifacts are stale for the current checkout

Severity: release blocker for final claims

Evidence:

The repo's own `evaluate_artifact_freshness()` marks these artifacts stale relative to current checkout:

- `var/reports/release-check-current.json`
- `var/reports/release-check-postgres-current.json`
- `var/reports/strict-release-check-current.json`
- `var/reports/release-readiness-check-current.json`
- `var/reports/live-operator-smoke-current.json`
- `var/reports/repo-local-status-current.json`

Why it matters:

Old green artifacts are useful historical evidence. They are not proof that this dirty tree is green now.

Minimum remediation:

- fix current checkout
- rerun gates on current tree
- regenerate artifacts with matching checkout/config freshness context

### P0-4. API/Hermes actor credentials are not stable in the current root

Severity: practical blocker for the user's intended service/API path

Evidence:

- `var/config/settings.yaml` does not persist `api.actor_policies`
- default actor policies are generated with `secrets.token_hex(...)`
- `/v1/retrieve` without actor returns `422`
- actor from a previous settings load returns `403 Invalid actor credentials`

Reproduced behavior:

```text
no_actor_status 422 Actor context is required for /v1/retrieve.
with_actor_from_prior_load_status 403 Invalid actor credentials for /v1/retrieve.
```

Why it matters:

The intended real use is not day-to-day CLI; it is seed once, then connect Hermes/API. If actor credentials are regenerated on load and not persisted, an external agent cannot reliably authenticate actor-scoped API calls.

Minimum remediation:

- persist stable owner/system actor policy credentials in local non-public config, or provide a supported operator command that prints/writes them once
- document the exact actor payload flow for Hermes
- add a regression test that an actor payload remains valid across separate settings loads/processes

### P0-5. README HTTP ingest examples are incomplete

Severity: practical blocker / docs-contract gap

Evidence:

- README shows `/v1/ingest/pipeline` curl examples without `actor`
- route code requires actor context for `/v1/ingest/pipeline`
- tests include actor payload

Why it matters:

The documented API seed-once path will fail as written. This directly affects the user's intended Hermes/API usage.

Minimum remediation:

- update README examples to include API token header plus valid actor payload
- or document a stable helper command for generating the actor block

### P1-1. Current docs tree contains stale plan documents that contradict active status if read as current

Severity: high documentation risk, not necessarily runtime blocker

Examples:

- `docs/agent_memory_go_live_plan.md` still says the checkout is not operationally ready because provider config is incomplete and storage is SQLite fallback
- `docs/programmer_agent_no_shortcuts_release_plan.md` still describes earlier hard blockers
- `dorabotka.md` still says live runtime may use mock and Postgres-first is not an operational gate

Why it matters:

Some of these are historical/remediation plans, but they are not all clearly marked as superseded. Future agents may read the wrong document as current.

Minimum remediation:

- add superseded headers to old plans
- keep active contract docs clearly listed in README

### P1-2. Review-gated wording is narrower than it sounds

Severity: product honesty issue

Evidence:

- `ingest-pipeline` auto-publishes validated candidates
- `needs_review` candidates are surfaced for review

Why it matters:

This is acceptable if "review-gated" means ambiguous or unsafe items require review. It is not accurate if it implies every extracted memory fact requires manual approval.

Minimum remediation:

- clarify wording: "validated candidates may auto-publish; ambiguous/unsafe candidates are review-gated"

### P1-3. Strict original brief remains NO-GO

Severity: not a private single-user blocker, but a strict spec mismatch

Evidence:

- original brief requires Docker Compose as part of P0a acceptance
- repo-local contract intentionally prefers no-Docker Postgres

Why it matters:

This is acceptable for Martin's single-machine private workflow if documented. It is not acceptable to claim strict original-brief completion as written.

Minimum remediation:

- keep the strict original track marked `NO-GO`, or explicitly amend/supersede the Docker wording

## What Is Actually Green

The following surfaces are good enough to count as real product progress:

- CLI command surface exists and is broad enough for technical owner operation
- ingest pipeline exists for seed-once use
- import and parsing support covers `text`, `markdown`, `chat`, `json`, `csv`, `email`, `pdf`
- core candidate/review/publish lifecycle exists
- retrieval is person-scoped and evidence-first
- refusal behavior is covered by tests/eval
- rollback correctness for superseded current-state facts is covered
- Postgres config path exists and DB reachability passed in operator preflight
- internal eval artifact passed `27/27`
- private core-loop test subset passed `38 passed`

## What Is Acceptably Out Of Scope For Martin's Single-User Use

These are not blockers for the stated private use:

- public signup/registration
- public profiles
- billing
- organization/team management
- public SaaS RBAC
- full admin UI
- broad multi-tenant productization
- strict Docker Compose operation on this machine, if no-Docker Postgres remains the accepted contract
- WhatsApp/Telegram parsers, because the active repo-local contract explicitly excludes them

## Honest Usability Answer

### Can it be used now?

Partially.

It can be used as a technical local prototype for exercising the memory loop and probably for controlled CLI experiments.

It should not yet be connected to real Hermes/API agent usage as a finished private memory service, because the current API actor credential path is unstable and the final gates are red.

### Does it fully match documentation under the one-user assumption?

No.

It matches the broad shape of the narrowed single-user contract, but it currently fails several requirements of that same narrowed contract:

- current docs-contract tests are red
- current release-readiness gate is red
- current artifacts are stale
- HTTP examples do not match API actor requirements
- actor credentials are not stable enough for an external Hermes agent

### Is the programmer-agent's "everything is done and functioning" claim accurate?

No.

A more accurate claim would be:

> The core private memory loop is substantially implemented and has passing focused tests/eval, but the current checkout is not final-release-ready. The API/Hermes integration path still needs stable actor credentials and fresh release-grade proof.

## Required Before Honest GO

1. Fix the `IMPLEMENTATION_NOTES.md` path mismatch and rerun `uv run pytest -q`.
2. Persist or generate stable local actor policies for API/Hermes use.
3. Update README HTTP examples to include API token and actor payload.
4. Run operator preflight with real provider env.
5. Run `release-readiness-check` with:
   - canonical Postgres
   - strict benchmark
   - operator-readiness
   - `MEMCO_RUN_LIVE_SMOKE=1`
   - valid live provider credentials
6. Regenerate `var/reports/*current*` artifacts after the checkout is fixed.
7. Mark stale remediation plans as historical/superseded or move them out of the active docs path.

## Evidence Index

Key local evidence used for this audit:

- Active repo-local contract: `docs/synthius_mem_execution_brief.md:15`, `docs/synthius_mem_execution_brief.md:29`, `docs/synthius_mem_execution_brief.md:60`
- Strict original reference status: `docs/2026-04-22_memco_original_brief_status.md:17`
- Current README contract split: `README.md:3`, `README.md:12`, `README.md:19`, `README.md:190`, `README.md:221`
- Stale/root implementation notes references: `README.md:51`, `docs/2026-04-21_memco_release_readiness_gate.md:68`, `tests/test_docs_contract.py:67`, `tests/test_docs_contract.py:168`
- API actor requirement: `src/memco/api/routes/retrieval.py:21`, `src/memco/api/routes/chat.py:22`, `src/memco/api/routes/ingest.py:87`
- Actor policy generation: `src/memco/config.py:25`, `src/memco/config.py:34`, `src/memco/config.py:154`
- Current local config missing live key and persisted actor policies: `var/config/settings.yaml:3`, `var/config/settings.yaml:7`, `var/config/settings.yaml:11`, `var/config/settings.yaml:12`
- Runtime fail-closed policy: `src/memco/llm.py:256`, `src/memco/llm.py:270`, `src/memco/llm.py:281`, `src/memco/llm.py:299`
- Final release-grade gate and live-smoke requirement: `src/memco/release_check.py:547`, `src/memco/release_check.py:577`, `src/memco/release_check.py:579`, `src/memco/release_check.py:607`
- Artifact freshness semantics: `src/memco/artifact_semantics.py:136`, `src/memco/artifact_semantics.py:152`, `src/memco/artifact_semantics.py:157`
- Operator preflight checks: `src/memco/operator_preflight.py:19`, `src/memco/operator_preflight.py:41`, `src/memco/operator_preflight.py:97`
- README HTTP seed examples missing actor: `README.md:125`, `README.md:140`
- Ingest pipeline auto-publish plus pending-review reporting: `src/memco/services/pipeline_service.py:71`, `src/memco/services/pipeline_service.py:82`, `src/memco/services/pipeline_service.py:96`

# Memco Contract Compliance Matrix

Date: 2026-04-24
Status: historical pre-remediation contract matrix, not current release verdict.
Current release verdict lives in `docs/2026-04-24_memco_release_closure.md`.
Audit package index: `docs/2026-04-24_memco_audit_package_index.md`
Source audit: `docs/2026-04-24_memco_final_release_audit.md`
Russian summary: `docs/2026-04-24_memco_final_release_audit_ru.md`
Evidence appendix: `docs/2026-04-24_memco_audit_evidence_appendix.md`
Remediation plan: `docs/2026-04-24_memco_release_remediation_plan.md`
Blocker ticket pack: `docs/2026-04-24_memco_blocker_ticket_pack.md`
Docs status map: `docs/2026-04-24_memco_docs_status_map.md`

## Purpose

This matrix maps documented requirements to the pre-remediation checkout audited on 2026-04-24.

For the current remediated private single-user verdict, use `docs/2026-04-24_memco_release_closure.md`.

It separates:

- active repo-local single-user contract
- strict original brief reference track
- requirements waived by Martin's one-user/private use case
- current blockers that remain even under the one-user/private assumption

## Status Vocabulary

| Status | Meaning |
|---|---|
| `green` | Implemented and current audit evidence supports it. |
| `partial` | Implemented in part, but current evidence is incomplete or operationally fragile. |
| `red` | Does not satisfy the relevant contract in the current checkout. |
| `waived-for-private` | Not required for Martin's current single-user private use. |
| `reference-track-red` | Still a mismatch with the strict original brief, but not an active blocker for the accepted repo-local private workflow. |

## Active Repo-Local Contract

Source: `docs/synthius_mem_execution_brief.md`

| Requirement | Documented source | Current audited status | Blocker for private GO? | Evidence / reason |
|---|---|---:|---:|---|
| Local/private/operator-controlled/review-gated product scope | `docs/synthius_mem_execution_brief.md`, `README.md` | `green` as scope decision | No | The narrowed scope is valid for Martin's stated use. |
| Public SaaS registration/profile/billing is not required | User constraint plus active repo-local scope | `waived-for-private` | No | One-user private product does not need public account/profile/billing UX. |
| CLI/local owner path may run without API actor payload | `docs/synthius_mem_execution_brief.md` Stage A operator model | `green` | No | CLI/dev core-loop subset passed. |
| User-facing API requires actor context | `docs/synthius_mem_execution_brief.md`, API routes | `partial` | Yes | Routes enforce actor context, but root actor credentials are not stable enough for real Hermes/API use. |
| Supported ingestion types: `text`, `markdown`, `chat`, `json`, `csv`, `email`, `pdf` | `docs/synthius_mem_execution_brief.md` Stage A ingestion scope | `green` for code/test coverage, not final release proof | No by itself | Focused tests and parser code exist; release gate is red for other reasons. |
| WhatsApp/Telegram parsers are out of current scope | `docs/synthius_mem_execution_brief.md` Stage A ingestion scope | `waived-for-private` | No | These remain roadmap/reference-track unless explicitly pulled into scope. |
| Conversation import | Stage A requires conversation import | `green` in focused coverage | No by itself | `tests/test_cli_smoke.py`, `tests/test_api_ingest_conversation.py`, and core subset passed. |
| Candidate extraction | Stage A requires candidate extraction | `green` in focused coverage | No by itself | CLI/API candidate tests exist; core subset passed. |
| Publish/reject/review resolution | Stage A requires publish/reject/review | `green` in focused coverage | No by itself | CLI smoke and review/candidate tests cover the path. |
| Supported retrieval | Stage A requires supported retrieval | `green` in focused coverage | No by itself | CLI/API retrieval tests exist; retrieval route requires actor. |
| Refusal on unsupported premise | Stage A requires refusal correctness | `green` in focused coverage | No by itself | CLI smoke checks unsupported premise refusal. |
| Rollback correctness | Stage A requires rollback correctness | `green` in focused coverage | No by itself | `tests/test_fact_lifecycle_rollback.py` passed in focused subset. |
| Regression coverage | Stage A requires regression coverage | `red` | Yes | Full suite is red: `2 failed, 345 passed`. |
| Documentation honesty | Stage A requires docs honesty | `red` | Yes | Docs/tests point to deleted root `IMPLEMENTATION_NOTES.md`; old green docs/artifacts can be read as current unless marked carefully. |
| Release-grade proof through canonical Postgres, operator readiness, and live smoke | `docs/synthius_mem_execution_brief.md`, release gate | `red` | Yes | `release-readiness-check` returned `ok=false`; live smoke skipped because release claim requires it. |
| No-Docker Postgres is accepted active local runtime | `docs/synthius_mem_execution_brief.md` Infrastructure Decision | `partial` in this audit | No by itself | Operator preflight found DB reachability and backup path ok, but release-grade Postgres steps were skipped due prior gate failures. |

## Strict Original Brief Reference Track

Source: `docs/synthius_mem_programmer_spec_v1_1_agent_ready.md`, `docs/2026-04-22_memco_original_brief_status.md`

| Requirement | Current audited status | Blocks active private GO? | Blocks strict original completion? | Evidence / reason |
|---|---:|---:|---:|---|
| PostgreSQL runtime plus migrations | `partial/green` | No by itself | No if using direct Postgres | Direct Postgres path exists; current release-grade gate did not reach Postgres smoke because earlier gates failed. |
| Docker Compose as explicit original brief requirement | `reference-track-red` | No | Yes | Active repo-local contract intentionally uses no-Docker Postgres; original wording still needs waiver/superseding for strict closure. |
| Actor-scoped request contract | `partial` | Yes | Yes until stable | Enforcement exists, but real-root credentials are unstable across settings loads. |
| Provider-agnostic LLM adapter | `partial/green structurally` | Yes for release proof | No structurally | Mock and OpenAI-compatible provider code exists; current operator shell lacks live `api_key`, so release runtime policy is red. |
| Token accounting | `green` in eval/private path | No by itself | No by itself | Eval artifact tracked token usage; live release proof still missing. |
| Generic source/provenance layer | `green` from implementation map | No | No by itself | Source documents/segments and retrieval provenance are present. |
| Candidate lifecycle and publish gates | `green` in focused coverage | No by itself | No by itself | Tests cover lifecycle and publish restrictions. |
| Expanded eval artifact | `green` | No by itself | No by itself | `eval-run` produced `27/27`. |
| `IMPLEMENTATION_NOTES.md` deviations file | `red` | Yes | Yes | Root file is deleted while docs/tests still require root path. |

## Current Blockers Under Single-User Assumption

These remain blockers even though Martin is the only user.

| Blocker | Severity | Why one-user mode does not waive it | Evidence |
|---|---:|---|---|
| Full test suite fails | P0 | A private product still needs its own regression suite green before release claims. | `uv run pytest -q` -> `2 failed, 345 passed`. |
| Release-grade gate fails | P0 | The real intended path is Hermes/API-backed memory, not only CLI fixture testing. | `release-readiness-check` -> `ok=false`. |
| Live provider env absent in current shell | P0 | One user still needs the live LLM/provider path to work for real agent use. | `runtime_policy.reason=openai-compatible provider is missing api_key`. |
| Existing green artifacts are stale | P0 | Stale artifacts do not prove the dirty checkout works now. | Freshness check reports all checked `var/reports/*current*` as `stale`. |
| API actor credentials unstable | P0 | Hermes/API integration needs stable actor auth across processes/requests. | Default actor policies regenerate tokens; prior-load actor returns 403. |
| README HTTP examples omit required actor | P1 | A one-user operator still needs runnable HTTP examples. | `/v1/ingest/pipeline` examples omit `actor`; route uses `require_actor=True`. |
| Historical/remediation docs can be misread as current | P1 | Future agents may follow stale `GO` or old blocker wording. | Current docs tree contains mixed GO snapshots and stale plans. |

## Accepted Non-Blockers For Martin's Current Product

| Item | Status | Reason |
|---|---:|---|
| Public registration | `waived-for-private` | Martin is the only intended user. |
| Public profile management | `waived-for-private` | Not needed for seed-once/private agent memory. |
| Billing/subscriptions | `waived-for-private` | Not a private local product requirement. |
| Organization/team ACL UX | `waived-for-private` | Current API actor model can stay owner/operator focused. |
| Public onboarding | `waived-for-private` | Operator documentation is enough for private use once accurate. |
| Docker Compose day-to-day workflow | `reference-track-red`, not active blocker | Active local contract accepts no-Docker Postgres; strict original track must still mark Docker mismatch honestly. |
| WhatsApp/Telegram parsers | `waived-for-private/reference-track backlog` | Current accepted ingestion scope excludes them. |

## Contradictions To Resolve In Documentation

| Contradiction | Current impact | Required resolution |
|---|---|---|
| `docs/synthius_mem_execution_brief.md` says Stage A release is green, but current audit release-readiness is red. | Misleads future agents and release claims. | Update wording to distinguish historical green from current dirty-checkout proof, or regenerate fresh green artifacts after fixes. |
| Release docs point to root `IMPLEMENTATION_NOTES.md`, but file is deleted. | Full suite failure and docs-contract failure. | Restore root file or consistently move all refs/tests to `docs/IMPLEMENTATION_NOTES.md`. |
| Strict original status says implementation notes are green, but current root notes are missing. | Strict original reference note is stale for this checkout. | Refresh strict original status after fixing notes path. |
| README says HTTP pipeline path exists, but examples omit required actor. | Operator may copy a failing curl example. | Add actor block and token guidance to HTTP examples. |
| Old green `var/reports/*current*` artifacts exist beside dirty checkout. | Agents may claim GO from stale artifacts. | Use artifact freshness as mandatory evidence before GO. |

## Release Decision

| Question | Answer |
|---|---|
| Is the product broadly fake or empty? | No. Core local/private memory behavior is materially implemented. |
| Can Martin test the CLI/dev core loop locally? | Yes, cautiously. |
| Is the current checkout fully compliant with the active single-user private contract? | No. Release proof, tests, actor credentials, and docs consistency are not green. |
| Is strict original brief completion satisfied? | No. Docker Compose remains a reference-track mismatch, and current notes-path drift also breaks strict evidence. |
| Are public profiles/registration required before Martin can use it? | No. |
| Should this be connected to the real Hermes agent loop today? | No. Fix P0 blockers and produce fresh green release-readiness proof first. |

## Minimum GO Criteria

The smallest honest private GO requires all of:

1. `uv run pytest -q` is green.
2. Root `IMPLEMENTATION_NOTES.md` mismatch is resolved.
3. API actor credentials are stable across settings loads/processes.
4. HTTP docs/examples include required actor payloads.
5. Release docs no longer imply stale artifacts are current proof.
6. `MEMCO_RUN_LIVE_SMOKE=1 uv run memco release-readiness-check --project-root /Users/martin/memco --postgres-database-url 'postgresql://martin@127.0.0.1:5432/postgres'` passes with live provider env.
7. The resulting artifacts are fresh for the current checkout and config.

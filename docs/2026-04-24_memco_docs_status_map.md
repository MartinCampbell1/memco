# Memco Docs Status Map

Date: 2026-04-24
Audit package index: `docs/2026-04-24_memco_audit_package_index.md`

## Purpose

This map classifies the docs tree so future agents do not treat historical plans or stale green snapshots as current release proof.

Rule: for the current remediated checkout, start with `docs/2026-04-24_memco_release_closure.md`.

## Current Release Closure

| File | Role | Current use |
|---|---|---|
| `docs/2026-04-24_memco_release_closure.md` | Current private release closure | Use for the current private Hermes/API-backed verdict and fresh evidence summary. |

Current private verdict:

```text
Final private Hermes/API-backed verdict: `GO`
```

## Pre-Remediation Audit Package

These files describe the pre-remediation audit verdict for the dirty checkout inspected on 2026-04-24. Keep them as baseline evidence, not as the current release verdict after remediation.

| File | Role | Current use |
|---|---|---|
| `docs/2026-04-24_memco_audit_package_manifest.json` | Machine-readable audit manifest | Use for agent/script summaries. |
| `docs/2026-04-24_memco_audit_package_integrity.md` | Audit package integrity note | Use to confirm links/JSON/fences. |
| `docs/2026-04-24_memco_privacy_secret_scan.md` | Lightweight privacy/secret scan note | Use before sharing/staging/publishing artifacts. |
| `docs/2026-04-24_memco_audit_package_index.md` | Entry point | Read first. |
| `docs/2026-04-24_memco_final_release_audit_ru.md` | Russian owner-facing verdict | Use for short answer to Martin. |
| `docs/2026-04-24_memco_contract_compliance_matrix.md` | Requirement matrix | Use to separate active contract, strict original brief, waivers, and blockers. |
| `docs/2026-04-24_memco_final_release_audit.md` | Full final audit | Use for main reasoning and blocker list. |
| `docs/2026-04-24_memco_audit_evidence_appendix.md` | Reproducible evidence | Use when validating or challenging findings. |
| `docs/2026-04-24_memco_release_remediation_plan.md` | Staged remediation plan | Use for phase-by-phase fix planning. |
| `docs/2026-04-24_memco_blocker_ticket_pack.md` | Implementation ticket pack | Use as programmer-agent work queue. |
| `docs/2026-04-24_memco_docs_status_map.md` | This file | Use to interpret the docs tree. |

Pre-remediation audit verdict:

```text
NO-GO for honest private Hermes/API-backed use until P0 blockers are fixed and fresh release-readiness proof is produced.
```

## Active Contract Documents

These define the accepted repo-local private/single-user scope. Use them with the current release closure and fresh artifact checks, not by treating older dated status language as standalone proof.

| File | Role | Current use | Caution |
|---|---|---|---|
| `docs/synthius_mem_execution_brief.md` | Authoritative current iteration scope | Use as the active contract baseline. | Its "Stage A ... green" wording is not current proof for the dirty checkout audited on 2026-04-24. |
| `docs/2026-04-22_memco_contract_decision.md` | Contract decision | Use to justify active repo-local brief precedence. | Does not itself prove current runtime readiness. |
| `docs/2026-04-21_memco_release_readiness_gate.md` | Active repo-local release gate document | Use for intended gate shape. | Proof still comes from a fresh `release-readiness-check` artifact with live smoke. |
| `docs/2026-04-21_memco_private_release_gate.md` | Private release checklist | Use as historical/checklist context. | Treat green wording as contingent on fresh release-grade proof. |
| `README.md` | Operator-facing project entry | Use after remediation. | HTTP examples now include actor payloads; status claims remain scoped to private/local use. |

## Strict Original Brief And Reference Specs

These are architecture/reference documents, not the current private-release gate.

| File | Role | Current use | Caution |
|---|---|---|---|
| `docs/synthius_mem_programmer_spec_v1_1_agent_ready.md` | Original agent-ready execution brief | Use for strict original acceptance wording and backlog. | Too broad for current private single-user release. |
| `docs/synthius_mem_programmer_spec.md` | Full master spec | Use as architecture reference. | Not the active minimum release contract. |
| `docs/comments.md` | Commentary on full spec | Use as design context only. | Not a release gate. |
| `docs/2604.11563v1.pdf` | Research/source PDF | Use as reference source only. | Do not treat as implementation status. |
| `docs/2026-04-22_memco_original_brief_track_decision.md` | Decision to move original brief to reference/backlog track | Use to explain strict-vs-active split. | Does not waive the original wording by itself. |
| `docs/2026-04-22_memco_original_brief_status.md` | Strict original brief status note | Use for reference-track status. | Strict original status remains separate from private release closure. |

## Infrastructure Notes

| File | Role | Current use | Caution |
|---|---|---|---|
| `docs/2026-04-22_postgres_without_docker.md` | No-Docker Postgres guide | Use for accepted local Postgres workflow. | Does not replace release-readiness proof. |
| `docs/2026-04-22_docker_engine_blocker.md` | Docker recovery/debug note | Historical/archive | Docker is reference-track unless Martin explicitly asks for Docker workflow. |

## Historical Audit And Pre-Remediation Evidence

These are useful evidence of prior states. Do not use them as current release status.

| File | Role | Current use |
|---|---|---|
| `docs/2026-04-21_memco_grounded_audit.md` | Pre-remediation grounded audit | Historical evidence only. |
| `docs/2026-04-21_memco_executive_verdict_ru.md` | Old Russian verdict | Historical evidence only. |
| `docs/2026-04-21_memco_blocker_matrix.md` | Old blocker matrix | Historical evidence only. |
| `docs/2026-04-21_memco_single_user_operator_check.md` | Old single-user operator check | Historical evidence only. |
| `docs/plans/2026-04-21_memco_release_gap_remediation.md` | Original remediation plan | Historical plan; not current work queue. |

## Remediation Plans And Work Queues

| File | Role | Current use | Caution |
|---|---|---|---|
| `docs/2026-04-24_memco_release_remediation_plan.md` | Pre-remediation staged plan | Historical plan for how the private release blockers were fixed. | Do not treat as current verdict; use release closure for current status. |
| `docs/2026-04-24_memco_blocker_ticket_pack.md` | Pre-remediation ticket pack | Historical ticket queue for the private release blockers. | Do not treat as current work queue without rechecking against release closure. |
| `docs/programmer_agent_no_shortcuts_release_plan.md` | Prior no-shortcuts plan | Useful supporting plan. | Some items may be partially remediated or superseded; compare against 2026-04-24 audit package. |
| `docs/agent_memory_go_live_plan.md` | Prior go-live remediation plan | Historical/supporting plan. | Its runtime claims can be stale relative to current checkout. |
| `docs/plans/2026-04-21_memco_full_fix_plan.md` | Earlier canonical full fix plan | Supporting context. | Superseded by 2026-04-24 audit package for current blockers. |
| `dorabotka.md` | Root-level remediation notes, outside `docs/` | Supporting context. | Should be marked historical/superseded if kept. |

## Resolved Post-Remediation State

Current private-release remediation state:

| Area | Current state |
|---|---|
| Implementation notes | root `IMPLEMENTATION_NOTES.md` is restored and `docs/IMPLEMENTATION_NOTES.md` is available as supporting docs context. |
| Test suite | `uv run pytest -q` passed with `358 passed`. |
| API actor docs | README HTTP examples include required actor payloads and shared API token guidance. |
| Runtime config | live OpenAI-compatible provider is configured in ignored local `var/config/settings.yaml`. |
| Release artifacts | `release-readiness-check-current.json` is fresh for checkout/config. |
| Live smoke artifact | `live-operator-smoke-current.json` is fresh for checkout/config. |
| Operator preflight artifact | `operator-preflight-current.json` is fresh for checkout/config. |

This resolved state is scoped to the private single-user Hermes/API-backed release path. It is not strict original-brief or public SaaS closure.

## Reading Rules For Future Agents

1. Start with `docs/2026-04-24_memco_release_closure.md` for the current verdict.
2. Use `docs/2026-04-24_memco_audit_package_index.md` only for pre-remediation baseline context.
3. Treat `var/reports/*current*` artifacts as proof only after freshness validation.
4. Keep active private release scope separate from strict original brief completion.
5. Keep public SaaS features out of scope unless Martin explicitly reopens them.
6. Do not treat fixture/eval green as live Hermes/API release proof.

## Current Document-Level Fixes Closed

| Fix | Resolution |
|---|---|
| Resolve `IMPLEMENTATION_NOTES.md` canonical location. | Root file restored; docs/tests now agree. |
| Add actor payloads to README HTTP examples. | API examples now include shared token plus actor block. |
| Add historical/superseded headers to old plans as needed. | Old plans/audits point to the release closure. |
| Refresh active gate/status docs after remediation. | Current private release closure records fresh artifact-backed evidence. |

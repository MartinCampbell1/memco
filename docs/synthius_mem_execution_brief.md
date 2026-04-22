# Repo-Local Execution Brief For Memco

Date: 2026-04-22
Status: current repo-local iteration scope

## Purpose

This file is the explicit current-iteration brief for this repository.

It exists to remove ambiguity between:

- the original execution brief in [synthius_mem_programmer_spec_v1_1_agent_ready.md](synthius_mem_programmer_spec_v1_1_agent_ready.md)
- the current repo-local operating contract that has emerged during implementation and verification

## Precedence

For ongoing repo-local work, this file is the authoritative current iteration scope.

Use it together with:

- [2026-04-21_memco_release_readiness_gate.md](2026-04-21_memco_release_readiness_gate.md)
- [2026-04-21_memco_private_release_gate.md](2026-04-21_memco_private_release_gate.md)
- [../IMPLEMENTATION_NOTES.md](../IMPLEMENTATION_NOTES.md)

The original brief remains the architecture/reference document and the source of the strict original acceptance wording.

## Contract Decision

Memco currently follows a two-stage repo-local contract:

1. Stage A: honest private single-user release
2. Stage B: convergence toward broad brief alignment without forcing Docker into the accepted local workflow on this machine

This means:

- private release readiness and strict original-brief readiness are not the same gate
- a verified no-Docker Postgres path is part of the accepted repo-local runtime contract
- Docker artifacts may remain in the repo, but Docker is not part of the recommended local workflow on this machine unless explicitly requested

## Infrastructure Decision

For the current repo-local brief, the accepted Postgres runtime requirement is:

- PostgreSQL through any reachable Postgres instance
- versioned SQL migrations
- successful Memco runtime boot with `MEMCO_STORAGE_ENGINE=postgres`

This repo-local brief does not require Docker Compose as part of the accepted operator workflow on this machine.

Important:

- this is a repo-local contract decision
- it does not retroactively rewrite the wording of the original brief
- any statement about strict original-brief completion must still account for the original Docker Compose wording explicitly

## Stage A Scope

Stage A is the honest private release.

Stage A requires:

- clean local bootstrap
- CLI-only operator flow from scratch
- conversation import
- candidate extraction
- publish / reject / review resolution
- supported retrieval
- refusal on unsupported premise
- rollback correctness
- regression coverage
- documentation honesty

Stage A operator model:

- owner-only local usage
- CLI/local path may run without API actor payload
- user-facing API still requires actor on `chat` / `retrieve`

## Stage B Scope

Stage B is broader architectural convergence relative to this repo-local brief.

Stage B includes:

- actor-scoped user-facing request contract
- provider-agnostic LLM adapter
- token accounting
- generic `source_documents` / `source_segments` provenance model
- stricter candidate lifecycle and publish gates
- PostgreSQL runtime plus migrations
- acceptance-style eval artifact

Stage B does not require Docker as part of the accepted day-to-day workflow on this machine.

## Current Verified State

As of this brief:

- Stage A private release: green
- no-Docker Postgres operational path: green
- strict original-brief completion: still a separate question, documented as `NO-GO` in the release gate until the original Docker wording is explicitly superseded or accepted as waived

## Decision Rule

If the question is:

- `Is Memco usable today by a private owner/operator?`
  - answer: `yes`

- `Can Memco run on Postgres today on this machine without Docker?`
  - answer: `yes`

- `Does this repo strictly satisfy the original execution brief text as written?`
  - answer: `not yet a clean yes`

## Change Discipline

Do not silently collapse these contracts again.

If future work changes the accepted product contract, update:

- this file
- [2026-04-21_memco_release_readiness_gate.md](2026-04-21_memco_release_readiness_gate.md)
- [../README.md](../README.md)
- [../IMPLEMENTATION_NOTES.md](../IMPLEMENTATION_NOTES.md)

# Implementation Notes

Date: 2026-04-21

## Current Release Contract

Memco currently implements a working local single-user vertical slice.

That means:

- one private owner/operator can run the system locally
- the core memory loop is real
- the repository has a verified no-Docker Postgres runtime path on this machine
- the preferred operational path on this machine is no-Docker Postgres, not Docker Desktop
- strict execution-brief completion is still not a clean claim while the original brief continues to name Docker Compose explicitly

## Confirmed Deviations From The Original Brief

### Infrastructure

- PostgreSQL is the canonical storage contract.
- SQLite remains available only as a compatibility/dev fallback and is not the canonical backend.
- The repository now includes an initial PostgreSQL + Docker Compose + versioned SQL migration path for the strict original-brief convergence track.
- The code also supports a no-Docker Postgres path through `MEMCO_STORAGE_ENGINE=postgres` plus `MEMCO_DATABASE_URL`.
- The no-Docker Postgres path is the recommended local runtime path on this machine.
- The Docker artifacts remain in the repo, but they are not part of the current operator workflow on this machine unless explicitly requested.
- Unless the brief is amended, Docker Compose remains an unresolved strict-brief item rather than something to silently wave away.

### Request Contract

- Stage A explicitly treats the current request model as an owner-only private exception.
- The private owner-only exception now applies to the CLI/local path, not to the user-facing API contract.
- The user-facing API contract for `chat` / `retrieve` requires an actor block.
- Retrieval is filtered by `allowed_person_ids` and `allowed_domains`.
- The default private release mode remains the Stage A owner-only local workflow through the CLI/local path.

### Candidate Lifecycle

- The candidate lifecycle is now stricter than the original private-slice queue:
  - `extracted_candidate`
  - `validated_candidate`
  - `needs_review`
  - `published`
  - `rejected`
- Clean extraction paths move to `validated_candidate`; ambiguous paths move to `needs_review`; publish only accepts `validated_candidate`.
- Explicit publish gates now enforce canonical key, payload, source-segment provenance, confidence threshold, and workspace/ambiguity checks.
- The current review-resolution path now supports the two main ambiguity closures implemented in this slice:
  - speaker-resolution ambiguity
  - relation-target ambiguity when the target person is supplied explicitly during review
- For the current architecture, this materially closes the original soft publish-path gap.

### Source Layer

- The code now includes both:
  - an explicit `source_documents` compatibility view
  - a generic `source_segments` layer
- Conversation messages are addressable as source segments.
- The current `sources` table remains the underlying storage table for the shipped slice, with `source_documents` as the explicit source-document contract surface.
- Conversation tables remain an indexed/convenience projection on top of that source-document/source-segment layer.
- This materially closes the generic source-layer gap for the current architecture, even though broader future ingestion formats may still add more segment types later.
- Current implemented ingestion sources for the accepted repo-local contract are `text`, `markdown`, `chat`, `json`, `csv`, `email`, `pdf`, and `html`.
- Markdown parsing stores YAML frontmatter in source metadata while keeping only the body in searchable parsed text.
- HTML parsing stores page title metadata and searchable visible text while dropping script/style-like noise.
- `WhatsApp` and `Telegram` parser support remain roadmap/reference-track items, not current repo-local contract claims.

### LLM / Provider Architecture

- The code now includes a provider-agnostic LLM layer with explicit `complete_json`, `complete_text`, `count_tokens`, and `estimate_cost` contracts.
- The shipped runtime now defaults to the `openai-compatible` provider path.
- The `mock` provider remains available only as an explicit fixture/test fallback and is no longer the silent runtime default.
- An OpenAI-compatible adapter now exists and is verified through a local compatible HTTP smoke path.
- The private acceptance/eval path still uses the explicit mock/deterministic fixture route where deterministic test behavior is required; that is a testing choice, not the runtime default.

### Evaluation Surface

- The repository now ships an acceptance-style eval artifact for the private slice.
- The current eval artifact includes tracked token-usage summaries.
- Token usage is now tracked for both:
  - the explicit mock/deterministic fixture path
  - the OpenAI-compatible provider path exercised in tests
- `token_accounting.production_accounting` now breaks usage down by extraction/planner/retrieval/answer stage, event-summed retrieved context tokens, amortized extraction cost per candidate, and source/person/domain cost groups. Unknown live-provider pricing is reported as `null` with `cost_status: "unknown"` rather than as zero; source/domain/person groups are attribution groups, not additive billing totals.
- This is still not the final strict original-brief acceptance/reporting closure.

### Consolidation Surface

- Fact consolidation now uses domain/category-scoped semantic duplicate keys before inserting a new fact, so equivalent payloads can merge evidence even when a candidate's canonical key differs.
- Duplicate detection is scoped by workspace, person, domain, and category; unrelated categories never merge solely because a canonical key collides.
- Current-state categories still supersede older active facts while preserving old fact evidence and historical retrieval.

### Operator Surface

- The current private release now has a CLI-only operator flow, including a dedicated `conversation-import` command for the `source -> conversation` step.
- `review-dashboard` provides the minimum review UX for the private slice: queue items, candidate cards, evidence preview, proposed merge/supersede action, and flags for sensitive, low-confidence, and psychometrics candidates.
- The operator surface is still intentionally narrow and optimized for a technical single-user local workflow, not for a broader multi-user or service-managed product shape.

## Practical Reading Guide

If you are deciding whether the repo is usable today:

- yes, for a technical private owner/operator
- yes, through the verified no-Docker Postgres path if you want Postgres without Docker

If you are deciding whether the repo fully satisfies the original execution brief:

- not strictly while Docker Compose remains an explicit brief requirement and the chosen local workflow intentionally avoids Docker

The current repo-local execution contract is documented in `docs/synthius_mem_execution_brief.md`.
The explicit decision to use that repo-local brief as the target contract for current repo-local work is documented in `docs/2026-04-22_memco_contract_decision.md`.
The original brief is now kept as a reference/backlog-only track for current repo-local release management in `docs/2026-04-22_memco_original_brief_track_decision.md`.

## Current Honest Claim

Use this wording for the current state:

`Working local single-user vertical slice with a verified no-Docker Postgres runtime path; strict original-brief completion remains open unless the brief's Docker Compose requirement is explicitly waived or replaced.`

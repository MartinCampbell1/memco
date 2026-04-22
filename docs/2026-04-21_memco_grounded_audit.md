# Memco Grounded Audit

Date: 2026-04-21  
Auditor: Codex  
Scope baseline: `docs/synthius_mem_programmer_spec_v1_1_agent_ready.md` first, `docs/synthius_mem_programmer_spec.md` second

Historical note:

- This audit is a pre-remediation snapshot.
- It is useful as historical evidence for what was wrong on 2026-04-21.
- It is not the active repo-local release gate or the current controlling contract.
- Current canonical docs:
  - [2026-04-21_memco_release_readiness_gate.md](2026-04-21_memco_release_readiness_gate.md)
  - [synthius_mem_execution_brief.md](synthius_mem_execution_brief.md)
  - [2026-04-22_memco_contract_decision.md](2026-04-22_memco_contract_decision.md)

## Audit method

This audit follows the grounded-audit workflow:

1. Treat the spec as advisory but authoritative for acceptance.
2. Verify claims against the real repository.
3. Separate:
   - real release gaps
   - acceptable single-user simplifications
   - broader full-spec backlog items

## Validation executed

- `uv run pytest -q` -> `68 passed`
- `uv run memco --help` -> CLI entrypoint works inside the project environment
- `uv run memco eval-run --root /Users/martin/memco` -> `7/7` cases passed
- Manual rollback reproduction for superseded facts -> bug reproduced

## Final gate

Final gate: NO-GO

Master criteria checked:

- P0a local infra
- JSON/plaintext ingestion
- person and speaker resolution
- candidate lifecycle
- evidence-backed retrieval
- refusal behavior
- eval/reporting
- rollback/history
- single-user usability

Validated:

- Core single-user memory loop exists and runs.
- Person-scoped retrieval works.
- Unsupported personal claims are refused.
- Candidate/review/rejected data does not leak into normal answer context.
- Plaintext and JSON conversation ingestion are implemented.
- Retrieval logging is privacy-aware and redacted.
- A real operator flow on a clean temporary root succeeded for bootstrap, person upsert, import, candidate extract, publish, retrieve, supported chat, and false-premise refusal.

Unverified:

- Real Docker/PostgreSQL deployment path, because the repo does not contain it.
- Full acceptance-sized golden report, because the implementation only ships a small eval harness.

Manual-stage progression detected:

- Yes.
- The project is being described as finished, but several acceptance items from the execution brief were replaced by narrower local equivalents without an explicit deviation document.

Preview-ready:

- true for a private local prototype
- Evidence: local CLI, API tests, and eval harness pass under `uv run`

Handoff-ready:

- true, but only if the handoff explicitly says this is a working single-user vertical slice rather than full spec completion
- Evidence: repository is runnable locally and the main gaps are identifiable and reproducible

## P0a gate snapshot

1. `docker compose up` starts DB + API -> fail
2. Migrations apply from empty DB -> partial
3. JSON fixture conversation imports -> pass
4. Plaintext fixture conversation imports -> pass
5. Speakers can be mapped to at least two persons -> pass
6. Chunks preserve source segment references -> partial
7. Mock LLM extraction for Biography / Preferences / Work -> fail
8. Invalid extraction output rejected or `needs_review` -> partial
9. Valid candidates with evidence consolidate into active facts -> pass
10. Duplicate candidates merge evidence -> pass
11. Conflicting current-state facts supersede or go to `needs_review` -> pass
12. CategoryRAG retrieves active facts for the correct person only -> pass
13. Cross-person contamination test passes -> pass
14. `/chat` or CLI answers supported questions -> pass
15. `/chat` or CLI refuses false-premise questions -> pass
16. Candidate / `needs_review` / rejected facts never appear in normal answer context -> pass
17. Golden eval report is generated -> partial
18. Unit/integration tests pass -> pass
19. Token usage and retrieval latency are logged at least roughly -> partial
20. `IMPLEMENTATION_NOTES.md` lists deviations -> fail

## Findings

### 1. Repo/local infra does not match the P0a contract

Finding:

- The execution brief requires FastAPI + PostgreSQL via Docker Compose + migrations.

Verdict:

- strong

Why:

- The real implementation uses SQLite bootstrapping and schema execution, not Docker/PostgreSQL/Alembic.

Evidence:

- Spec requires PostgreSQL and Docker Compose: `docs/synthius_mem_programmer_spec_v1_1_agent_ready.md:49-56`
- Spec binary gates require `docker compose up` and migrations from empty DB: `docs/synthius_mem_programmer_spec_v1_1_agent_ready.md:346-347`
- Actual runtime initializes local directories and DB directly: `src/memco/runtime.py:14-20`
- Actual DB layer uses `sqlite3` and `executescript(schema.sql)`: `src/memco/db.py:10-17`, `src/memco/db.py:52-55`
- Storage config defaults to SQLite: `src/memco/config.py:22-25`
- Repo root does not contain `docker-compose.yml` or `alembic.ini`

Grounded reformulation:

- The project implements a local single-file SQLite runtime instead of the specified containerized PostgreSQL stack.

### 2. User-facing API contract omits required actor/viewer scope

Finding:

- The brief requires every user-facing request to include actor/viewer context, even in P0a.

Verdict:

- strong

Why:

- The API only supports a shared token. It does not accept or enforce actor identity, allowed person scope, domain scope, or sensitivity scope.

Evidence:

- Required actor context: `docs/synthius_mem_programmer_spec_v1_1_agent_ready.md:272-310`
- Actual request model omits actor entirely: `src/memco/models/retrieval.py:38-49`
- `/v1/chat` accepts `RetrievalRequest` directly: `src/memco/api/routes/chat.py:14-31`
- `/v1/retrieve` accepts `RetrievalRequest` directly: `src/memco/api/routes/retrieval.py:13-24`
- Auth only checks `MEMCO_API_TOKEN`: `src/memco/api/deps.py:16-38`

Grounded reformulation:

- The project has a working private auth stub, but not the actor-scoped request contract required by the brief.

### 3. Generic source layer is missing

Finding:

- The brief asks for a generic `source_documents` / `source_segments` model so conversations are only one source type, not the whole abstraction.

Verdict:

- strong

Why:

- The current schema is conversation-centric. It supports source files and chunks, but not the required generic segment model and not evidence keyed by `source_segment_ids`.

Evidence:

- Required generic source layer: `docs/synthius_mem_programmer_spec_v1_1_agent_ready.md:205-239`
- Actual schema uses `sources`, `source_chunks`, `conversations`, `conversation_messages`, `conversation_chunks`: `src/memco/schema.sql:1-145`
- Evidence points to `source_id` and optional `chunk_id`, not source segment ids: `src/memco/schema.sql:189-198`

Grounded reformulation:

- The implementation supports provenance for current chat-style ingestion, but not the future-proof source-segment abstraction required by the brief.

### 4. Candidate lifecycle is weaker than specified

Finding:

- The brief defines a richer lifecycle with `extracted_candidate`, `validated_candidate`, and explicit promotion rules before a fact becomes active.

Verdict:

- strong

Why:

- The implementation collapses candidate states to `candidate`, `needs_review`, `published`, `rejected`. There is no explicit validated stage.

Evidence:

- Required state machine and promotion rules: `docs/synthius_mem_programmer_spec_v1_1_agent_ready.md:151-199`
- Actual allowed candidate statuses: `src/memco/repositories/candidate_repository.py:8-9`
- Candidate insertion starts directly at `candidate`: `src/memco/repositories/candidate_repository.py:60-90`
- Review approval moves back to `candidate`, not `validated_candidate`: `src/memco/services/review_service.py:41-61`
- Publish moves directly from `candidate` / `needs_review` to `published`: `src/memco/services/publish_service.py:22-65`

Grounded reformulation:

- The candidate lifecycle works, but it is a simplified publish queue rather than the stricter staged lifecycle described in the brief.

### 5. Promotion gates are incomplete

Finding:

- Active facts should only appear after validation, evidence, confidence threshold, and conflict checks.

Verdict:

- strong

Why:

- Publishing only enforces resolved person plus evidence presence. No configured confidence gate or explicit hard-conflict block exists.

Evidence:

- Required promotion rules: `docs/synthius_mem_programmer_spec_v1_1_agent_ready.md:189-199`
- Publish checks only status, `person_id`, and evidence: `src/memco/services/publish_service.py:31-37`
- Fact add path auto-merges or supersedes but does not reject low-confidence publish: `src/memco/repositories/fact_repository.py:150-274`

Grounded reformulation:

- The system prevents obviously unresolved publishes, but it does not implement the full acceptance-grade promotion gate from the brief.

### 6. Rollback of superseded facts is incorrect

Finding:

- Rollback should be reversible and preserve a coherent truth store.

Verdict:

- strong

Why:

- Rolling back a `superseded` operation reactivates the old fact but leaves the newer fact active. That produces two active current-state facts at once.

Evidence:

- Rollback code only reactivates the old fact: `src/memco/repositories/fact_repository.py:340-363`
- It does not demote the newer fact referenced by `superseded_by_fact_id`
- Manual reproduction on 2026-04-21 showed both Berlin and Lisbon residence facts left in `active`
- Existing rollback coverage only tests delete rollback, not supersede rollback: `tests/test_fact_lifecycle_rollback.py:1-61`

Grounded reformulation:

- The diff engine supports delete/restore reasonably, but supersede rollback is not safely reversible yet.

### 7. Eval/reporting does not satisfy the brief

Finding:

- The brief requires a 20-50 question eval set and a report including accuracy, refusal correctness, evidence coverage, token estimate, and retrieval latency.

Verdict:

- strong

Why:

- The shipped eval harness is a compact 7-case smoke report. It does not produce the requested acceptance report shape.

Evidence:

- Spec eval requirement: `docs/synthius_mem_programmer_spec_v1_1_agent_ready.md:105-108`
- Spec acceptance gate requires golden eval report: `docs/synthius_mem_programmer_spec_v1_1_agent_ready.md:362-365`
- Minimal fixture requirement shows broader coverage expectations: `docs/synthius_mem_programmer_spec_v1_1_agent_ready.md:396-427`
- Actual eval cases count: `src/memco/services/eval_service.py:31-59`
- Actual report shape: `src/memco/services/eval_service.py:127-177`
- CLI just prints that JSON: `src/memco/cli/main.py:565-575`

Grounded reformulation:

- The project has a useful smoke eval, not a spec-complete acceptance harness.

### 8. `IMPLEMENTATION_NOTES.md` is missing

Finding:

- The brief explicitly requires documenting deviations from the full spec.

Verdict:

- strong

Why:

- Several deviations exist, but the required deviation document is absent.

Evidence:

- Acceptance gate 20: `docs/synthius_mem_programmer_spec_v1_1_agent_ready.md:365`
- No `IMPLEMENTATION_NOTES.md` present in repo root

Grounded reformulation:

- The project does not yet contain the honesty layer the brief asks for when scope is narrowed or infra differs.

### 9. Provider-agnostic LLM layer is absent

Finding:

- The brief requires a mock LLM provider for CI and an OpenAI-compatible provider interface.

Verdict:

- strong

Why:

- The repository has only LLM config fields, but no `LLMClient`, no provider adapter module, and no actual extraction path that goes through a mock/OpenAI-compatible client.

Evidence:

- Brief requires mock + OpenAI-compatible provider: `docs/synthius_mem_programmer_spec_v1_1_agent_ready.md:55-56`
- Full reference requires provider-agnostic adapter and mock provider: `docs/synthius_mem_programmer_spec_v1_1_agent_ready.md:857-871`
- Repo has no `llm/` package or equivalent; file inventory under `src/memco` contains no provider/client module
- Only LLM-related code is config fields: `src/memco/config.py:17-20`, `src/memco/config.py:91-113`

Grounded reformulation:

- The current project implements deterministic rule-based extraction instead of the specified LLM adapter architecture.

### 10. Token accounting is missing, while latency logging is present

Finding:

- The brief requires rough token usage and retrieval latency logging.

Verdict:

- strong

Why:

- Retrieval latency is stored, but there is no token accounting surface because no LLM adapter exists and no token counters are logged anywhere.

Evidence:

- Acceptance gate mentions token usage + retrieval latency: `docs/synthius_mem_programmer_spec_v1_1_agent_ready.md:364`
- Retrieval logs store `latency_ms`: `src/memco/schema.sql:270`, `src/memco/services/retrieval_service.py:29-56`
- No `count_tokens`, `estimate_cost`, or token counter implementation exists in the repo

Grounded reformulation:

- Observability is only partial: latency exists, token accounting does not.

### 11. End-to-end CLI operator flow is incomplete

Finding:

- A real private operator can use the system, but not all required steps are exposed cleanly through the CLI alone.

Verdict:

- strong for ergonomics
- weak as a core correctness blocker

Why:

- The CLI supports `init-db`, `import`, `candidate-extract`, `candidate-publish`, `retrieve`, `chat`, and eval commands, but it does not expose a command to turn an imported source into a conversation. That forces the operator to use the API route or a direct service call for the `source_id -> conversation_id` step.

Evidence:

- Present CLI commands: `src/memco/cli/main.py:36-575`
- Operator validation on 2026-04-21 succeeded only after calling `ConversationIngestService().import_conversation(...)` directly for the conversation-import step
- API route for this step exists: `src/memco/api/routes/ingest.py:55-74`

Grounded reformulation:

- The system is usable for a private operator, but the CLI is not yet a complete single-surface workflow.

### 12. Some apparent issues are acceptable or only weakly grounded

Finding:

- Not every divergence from the full master spec is a release blocker for single-user private use.

Verdict:

- weak / unsupported as blockers

Why:

- The user explicitly narrowed the product context to one private operator, so multi-user registration/profile/RBAC surfaces are not required for practical use.

Evidence:

- Full auth matrix is out of scope in P0a anyway: `docs/synthius_mem_programmer_spec_v1_1_agent_ready.md:117-119`
- Core refusal, retrieval, ingestion, and person scoping are covered by passing tests
- Plaintext support exists and is tested: `tests/test_conversation_ingest_service.py:50-129`
- Retrieval log redaction exists and is tested: `tests/test_retrieval_logging.py:13-125`

Grounded reformulation:

- Missing full auth/RBAC is not the main problem for the current private use case. The real blockers are infrastructure mismatch being undocumented, incomplete lifecycle gating, and the rollback defect.

## What is already good

- Core single-user workflow is real, not mocked.
- JSON and plaintext conversation ingestion both work.
- Explicit person resolution and manual speaker resolution are present.
- Retrieval is person-scoped.
- Unsupported personal claims are refused rather than hallucinated.
- Retrieval logs avoid storing raw query text or fallback chunk text.
- Style and psychometrics do not leak into factual answers.

## Single-user verdict

If the question is:

- "Is this fully compliant with the documentation?" -> no.
- "Can I personally use it now as a private local tool?" -> yes, with caution.

Practical single-user verdict:

- usable as a private prototype
- not acceptable as an honestly completed implementation of the execution brief

## Required before honest done

1. Fix supersede rollback so only one current-state fact remains active after reversal.
2. Add `IMPLEMENTATION_NOTES.md` and explicitly record all scope/infra deviations.
3. Either:
   - implement Docker/PostgreSQL/migrations, or
   - rewrite the execution brief for a SQLite-only private local slice.
4. Expand eval from the current 7-case smoke report to the required acceptance report.
5. Decide whether the actor-scoped contract is still mandatory for this repo; if not, document the single-user exception explicitly.

# Current Status

Status: current checkout status entrypoint.

Current verdict: P0 semantic remediation is green for the private single-user agent-memory pilot code path, based on the fresh local gate evidence listed below. The live/Postgres release-grade artifacts are fresh for this exact checkout and pass. Do not derive this verdict from historical documents.

Accepted working scope: private, single-user, local/operator-controlled, review-gated agent memory for a technical owner. See [PRIVATE_SINGLE_USER_CONTRACT.md](PRIVATE_SINGLE_USER_CONTRACT.md).

Strict original/PDF parity status: not complete; reference-track gaps remain. See [PDF_PARITY_GAPS.md](PDF_PARITY_GAPS.md).

Current reproduction path: [LOCAL_REPRODUCTION.md](LOCAL_REPRODUCTION.md).

Historical dated reports, release closures, audits, remediation plans, and ticket packs are evidence only. If a dated document says GO or NO-GO, treat that as the verdict for that document's snapshot, not for the current checkout.

Current phase context for this current checkout:

- P0.1: fresh runtime gates are current for this current checkout, including Postgres/live-provider release readiness and live operator smoke.
- P0.2/P0.3: dense multi-fact messages are covered by a private-agent e2e regression and extraction now runs on atomic clauses while preserving original message/source provenance.
- P0.4/P0.5: preference current/past extraction and work role/tool extraction are fixed and regression-tested.
- P0.6: AnswerService has deterministic field-aware synthesis for residence, work tools, preferences, social relations, and experience fields.
- P0.7: `memco eval personal-memory` now includes a realistic dense personal-message bucket that runs real ingest/extract/publish/retrieve/answer flow and must pass 30/30.
- P0.8: overcaptured provider payloads and source-mismatched residence candidates are forced to review instead of publish.
- Selected P1: preference evolution queries for current/history/still-like behavior are regression-tested.
- Selected P1: experiences now include normalized `event_type`/`salience`, indexed temporal/location/participant/outcome/lesson retrieval, a `build-life-timeline` CLI, and regression coverage for life-change queries after confirmed events.
- Selected P1: social-circle acceptance queries for sister, best friend, close people, event participants, and known people are regression-tested.
- Selected P1: work outcome/collaborator acceptance queries for accomplishments and work-with retrieval are regression-tested.
- Selected P1: planner private mode now runs deterministic planning first and only calls the LLM planner for low-confidence or multi-domain queries; provider output stays schema/domain-validated and fail-closed when selected.
- Selected P1: `memco eval personal-memory` now includes a P1.8 private eval target report with the auditor's stronger bucket counts and thresholds; the fixture/private target counts and thresholds pass for the internal 840-case suite, while the report remains explicitly not paper-equivalent.
- Selected P1: answer guardrails reject prompt-injection attempts that ask the system to ignore memory and state unsupported personal facts.
- Selected P1: psychometrics remain explicit opt-in, non-factual, counterevidence/confidence-gated, and do not answer personality questions from one low-confidence signal.
- Selected P1: `memco private-pilot-gate` now produces a `private_pilot_gate_report` with explicit checks for semantic pytest, personal-memory eval, backup export/verify/restore dry-run, retrieval-only API smoke, unsupported-claim refusal, evidence coverage, pending-review non-leakage, and no benchmark-mode leakage.
- Selected P2: structured parser messages now carry source document, source segment, and locator metadata for chat/email-style imports.
- Selected P2: Markdown journal imports now create heading-based source segments and inline note imports now create `inline_note` source segments with file/origin/character locator metadata.
- Selected P2: `memco eval personal-memory` now includes a P2.1 external benchmark report that explicitly records public/external LoCoMO as `not_run` and keeps `ok_for_pdf_score_claim=false`; internal LoCoMO-like fixtures remain not paper-equivalent.
- Selected P2: `memco eval personal-memory` now includes an internal synthetic long-corpus stress smoke covering JSON conversation ingest, extraction cost, candidate volume, fact growth, retrieval latency, false-positive retrieval, and refusal quality. Its P2.3 target report explicitly keeps full P2.3 `ok_for_full_p2_3_claim=false` until 50k/500k-message and mixed-source stress are actually run; this is not a paper-equivalent benchmark claim.
- Selected P2: existing token/latency accounting remains covered by eval harness tests and `memco verify-current-status` now fail-closes missing token/latency fields in the current eval artifact; no new PDF-score claim is made here.
- Selected benchmark Phase 3: `memco benchmark locomo` now runs the shared LoCoMo harness core, writes manifest/backend/raw-answer/judge/cache artifacts, supports resume caching, and keeps optional public adapters skippable instead of failing the run.
- Selected benchmark Phase 4: mandatory non-external baselines are implemented for `full_context`, `sliding_window`, `summarization`, and `embedding_rag`, with deterministic test answer/embed providers and schema-compatible benchmark outputs.
- Selected benchmark Phase 5: `memco` is available as a LoCoMo benchmark backend with per-sample isolated sqlite runtime roots, explicit benchmark-mode auto-publish guardrails, LoCoMo speaker-to-person mapping, retrieval/answer outputs, evidence ids, pending/published counts, and target-unknown skips.
- Selected benchmark Phase 6: benchmark judging, category metrics, PDF-style taxonomy mapping, comparison tables, cached judge outputs, and deterministic decision reporting are implemented for the LoCoMo harness.
- Selected benchmark Phase 7: Mem0, Zep, and LangMem are wired as optional public adapters through the shared benchmark backend interface; missing run flags, SDKs, or credentials skip cleanly without changing core dependencies.
- Selected benchmark Phase 8: Memco now exposes explicit LLM-first extraction schema modules, token-bounded conversation chunking with overlap, planner CategoryRAG field constraints, redacted retrieval-log constraint visibility, temporal current/past coverage, and opt-in psychometrics guardrails.
- Selected benchmark Phase 9: the full mandatory LoCoMo harness run over `external/locomo/data/locomo10.json` completes for all mandatory backends with fixture providers and writes comparison, decision, raw-answer, judge-log, cache, and manual-audit artifacts. The requested `gpt-4.1-mini`/`text-embedding-3-small` dry-run is preserved as a failed artifact because the configured provider returned chat `HTTP 503` and embeddings `HTTP 405`; no live benchmark quality claim is made from the fixture run. A later live dry-run using `gpt-5.4-mini` through the local OpenAI-compatible gateway and OpenRouter embeddings completed for baseline/RAG backends, plus a capped Memco ingestion smoke with `--memco-max-ingest-chunks 2`; this is live-smoke evidence only, not a full uncapped live LoCoMo Memco claim.
- Fixture/repo-local artifacts listed below are refreshed for this current checkout.
- Live/Postgres release artifacts listed below are refreshed in an operator shell with Postgres URL, live-smoke request, and live-provider credentials.

Fresh gate evidence for this checkout:

- `uv run pytest -q`: 723 passed.
- `uv run pytest tests/test_private_agent_semantic_regressions.py -q`: 14 passed.
- `uv run pytest tests/test_benchmark_runner.py -q`: 7 passed.
- `uv run pytest tests/test_benchmark_baselines.py tests/test_benchmark_runner.py -q`: 13 passed.
- `uv run pytest tests/test_benchmark_memco_backend.py tests/test_benchmark_baselines.py tests/test_benchmark_runner.py -q`: 23 passed.
- `uv run pytest tests/test_benchmark_judge.py tests/test_benchmark_metrics.py tests/test_benchmark_reports.py tests/test_benchmark_runner.py tests/test_benchmark_baselines.py tests/test_benchmark_memco_backend.py tests/test_locomo_loader.py tests/test_benchmark_mode_does_not_disable_review_gate.py -q`: 47 passed.
- `uv run pytest tests/test_benchmark_optional_adapters.py tests/test_benchmark_runner.py -q`: 11 passed.
- `uv run pytest tests/test_chunking.py tests/test_planner_category_rag.py tests/test_config.py tests/test_extraction_contracts.py::test_extraction_prompt_contract_exposes_llm_first_domain_rules tests/test_extraction_contracts.py::test_prompt_payload_embeds_output_contract tests/test_extraction_contracts.py::test_phase8_structured_extraction_modules_expose_domain_contracts tests/test_llm_provider.py::test_extraction_service_openai_compatible_provider_path_covers_llm_first_regressions tests/test_retrieval_service.py::test_domain_retrievers_expose_category_rag_contracts tests/test_retrieval_logging.py::test_retrieval_logs_include_redacted_category_rag_constraints tests/test_style_psychometric_guardrails.py::test_style_and_psychometrics_do_not_answer_factual_questions tests/test_style_psychometric_guardrails.py::test_psychometrics_do_not_surface_in_retrieve_results tests/test_benchmark_memco_backend.py tests/test_benchmark_baselines.py tests/test_benchmark_runner.py tests/test_private_agent_semantic_regressions.py -q`: 73 passed.
- `uv run memco benchmark locomo --dataset tests/fixtures/locomo_mini.json --backends full_context --output-dir var/reports/benchmark-current/phase3-smoke --no-judge`: `ok=true`, 3 raw answers written, runner artifacts present.
- `uv run memco benchmark locomo --dataset tests/fixtures/locomo_mini.json --backends full_context,sliding_window,summarization,embedding_rag --output-dir /tmp/memco-phase4-smoke --answer-model fixture --embedding-model fixture-embedding --no-judge`: `ok=true`, all four mandatory baselines wrote reports.
- `uv run memco benchmark locomo --dataset tests/fixtures/locomo_mini.json --backends memco --output-dir /tmp/memco-phase5-smoke --answer-model fixture --no-judge --benchmark-mode`: `ok=true`, isolated Memco runtime used, manual review false, benchmark auto-publish true.
- `uv run memco benchmark locomo --dataset tests/fixtures/locomo_mini.json --backends full_context,sliding_window,summarization,embedding_rag,memco --output-dir var/reports/benchmark-current --answer-model fixture --judge-model fixture-judge --embedding-model fixture-embedding --benchmark-mode --force`: `ok=true`, judge calls cached, comparison summary tables and deterministic decision report written.
- `uv run memco benchmark locomo --dataset tests/fixtures/locomo_mini.json --backends mem0,zep,langmem --output-dir /tmp/memco-phase7-smoke --answer-model fixture --judge-model fixture-judge`: `ok=true`, all optional public adapters skipped because `MEMCO_RUN_VENDOR_BENCHMARKS` is not enabled.
- `uv run memco benchmark locomo --dataset tests/fixtures/locomo_mini.json --backends memco --output-dir /tmp/memco-phase8-smoke --answer-model fixture --judge-model fixture-judge --benchmark-mode --extraction-mode llm_first`: `ok=true`, Memco mini fixture ingestion used benchmark auto-publish and wrote planner field constraints into raw benchmark answers.
- `uv run memco benchmark locomo --dataset external/locomo/data/locomo10.json --backends memco,full_context,sliding_window,summarization,embedding_rag --answer-model gpt-4.1-mini --judge-model gpt-4.1-mini --embedding-model text-embedding-3-small --output-dir var/reports/benchmark-dry-run --max-samples 1 --max-questions 20 --benchmark-mode --force`: `ok=false`, requested live dry-run blocked by provider `HTTP 503` for chat and `HTTP 405` for embeddings; artifact retained as failure evidence.
- `uv run memco benchmark locomo --dataset external/locomo/data/locomo10.json --backends full_context,sliding_window,summarization,embedding_rag --answer-model gpt-5.4-mini --judge-model gpt-5.4-mini --embedding-model openai/text-embedding-3-small --output-dir var/reports/benchmark-dry-run-live-baselines --max-samples 1 --max-questions 20 --force`: `ok=true`, 20-question live smoke completed with judge errors 0; accuracies were full_context 0.65, sliding_window 0.55, summarization 0.60, embedding_rag 0.60.
- `uv run memco benchmark locomo --dataset external/locomo/data/locomo10.json --backends memco --answer-model gpt-5.4-mini --judge-model gpt-5.4-mini --embedding-model openai/text-embedding-3-small --output-dir var/reports/benchmark-dry-run-live-memco --max-samples 1 --max-questions 20 --benchmark-mode --extraction-mode combined_legacy --memco-max-ingest-chunks 2 --force`: `ok=true`, capped live Memco smoke completed with judge errors 0, accuracy 0.55, evidence coverage 1.0, and `max_ingest_chunks=2`; this is not a full uncapped live Memco benchmark.
- `uv run memco benchmark locomo --dataset external/locomo/data/locomo10.json --backends memco,full_context,sliding_window,summarization,embedding_rag --answer-model fixture --judge-model fixture-judge --embedding-model fixture-embedding --output-dir var/reports/benchmark-current --benchmark-mode --force`: `ok=true`, full 10-conversation/1542-question mandatory fixture run completed.
- `var/reports/benchmark-current/manual_audit.md`: created for the full mandatory fixture run; recommendation is inconclusive/fix Memco before private use, with no public/live quality claim.
- `uv run memco private-pilot-gate --project-root . --root /tmp/memco-private-pilot-gate --output var/reports/private-pilot-gate-current.json`: `ok=true`, 840/840 personal-memory eval, unsupported-as-fact 0, supported-missing-evidence 0, pending-confirmed leakage 0.
- `uv run memco verify-current-status --project-root . --pytest-passed 723`: passes with current artifact freshness.
- `var/reports/personal-memory-eval-current.json`: fresh fixture/internal eval proof for this current checkout; 840/840 passed.
- `var/reports/release-check-current.json`: fresh quick repo-local release-check proof for this current checkout; acceptance 27/27.
- `var/reports/local-artifacts-refresh-current.json`: fresh repo-local refresh summary for this current checkout; full suite 723 passed, contract stack 105 passed, release-check acceptance 27/27.
- `var/reports/release-readiness-check-current.json`: fresh release-grade artifact for this current checkout; `ok=true`.
- `var/reports/live-operator-smoke-current.json`: fresh live-smoke artifact for this current checkout; `ran=true`, `ok=true`, and supported chat used planner `v2_llm`.
- Independent critic gates are supporting evidence only; do not use critic names as a substitute for validating the current artifacts.

Supporting legacy smoke evidence:

- `var/reports/manual-p0-smoke-current.json`: ok=true, 19/19 manual P0 smoke checks. This is an ad-hoc legacy artifact without `artifact_context`; do not use it as freshness-gated checkout proof.

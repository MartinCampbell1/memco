# Current Status

Status: current checkout status entrypoint.

Current verdict: P0 semantic remediation is green for the private single-user agent-memory pilot code path, based on the fresh local gate evidence listed below. Release-grade GO still requires refreshing the live/Postgres artifacts for this exact checkout. Do not derive this verdict from historical documents.

Accepted working scope: private, single-user, local/operator-controlled, review-gated agent memory for a technical owner. See [PRIVATE_SINGLE_USER_CONTRACT.md](PRIVATE_SINGLE_USER_CONTRACT.md).

Strict original/PDF parity status: not complete; reference-track gaps remain. See [PDF_PARITY_GAPS.md](PDF_PARITY_GAPS.md).

Current reproduction path: [LOCAL_REPRODUCTION.md](LOCAL_REPRODUCTION.md).

Historical dated reports, release closures, audits, remediation plans, and ticket packs are evidence only. If a dated document says GO or NO-GO, treat that as the verdict for that document's snapshot, not for the current checkout.

Current phase context for this dirty worktree:

- P0.1/P0.2: memory explorer help contract is green; private semantic regression suite added.
- P0.3: current-vs-historical preference retrieval is fixed and regression-tested.
- P0.4: compound sister/best-friend extraction and relation retrieval are fixed and regression-tested.
- P0.5/P0.6: accident location and event-specific temporal retrieval are fixed and regression-tested.
- P0.7: `memco verify-current-status` now fail-closes stale docs/artifacts instead of trusting hardcoded claims.
- Selected P1: preference evolution queries for current/history/still-like behavior are regression-tested.
- Selected P1: experiences now include normalized `event_type`/`salience`, indexed temporal/location/participant/outcome/lesson retrieval, a `build-life-timeline` CLI, and regression coverage for life-change queries after confirmed events.
- Selected P1: social-circle acceptance queries for sister, best friend, close people, event participants, and known people are regression-tested.
- Selected P1: work outcome/collaborator acceptance queries for accomplishments and work-with retrieval are regression-tested.
- Selected P1: planner private mode now runs deterministic planning first and only calls the LLM planner for low-confidence or multi-domain queries; provider output stays schema/domain-validated and fail-closed when selected.
- Selected P1: `memco eval personal-memory` now includes a P1.8 private eval target report with the auditor's stronger bucket counts and thresholds; the fixture/private target counts and thresholds pass for the internal 840-case suite, while the report remains explicitly not paper-equivalent.
- Selected P1: answer guardrails reject prompt-injection attempts that ask the system to ignore memory and state unsupported personal facts.
- Selected P1: psychometrics remain explicit opt-in, non-factual, counterevidence/confidence-gated, and do not answer personality questions from one low-confidence signal.
- Selected P2: structured parser messages now carry source document, source segment, and locator metadata for chat/email-style imports.
- Selected P2: Markdown journal imports now create heading-based source segments and inline note imports now create `inline_note` source segments with file/origin/character locator metadata.
- Selected P2: `memco eval personal-memory` now includes a P2.1 external benchmark report that explicitly records public/external LoCoMO as `not_run` and keeps `ok_for_pdf_score_claim=false`; internal LoCoMO-like fixtures remain not paper-equivalent.
- Selected P2: `memco eval personal-memory` now includes an internal synthetic long-corpus stress smoke covering JSON conversation ingest, extraction cost, candidate volume, fact growth, retrieval latency, false-positive retrieval, and refusal quality. Its P2.3 target report explicitly keeps full P2.3 `ok_for_full_p2_3_claim=false` until 50k/500k-message and mixed-source stress are actually run; this is not a paper-equivalent benchmark claim.
- Selected P2: existing token/latency accounting remains covered by eval harness tests and `memco verify-current-status` now fail-closes missing token/latency fields in the current eval artifact; no new PDF-score claim is made here.
- Fixture/repo-local artifacts listed below are refreshed for this dirty checkout.
- Live/Postgres release artifacts listed below are historical until regenerated in an operator shell with Postgres URL, live-smoke request, and live-provider credentials.

Fresh gate evidence for this checkout:

- `uv run pytest -q`: 632 passed.
- `uv run pytest tests/test_private_agent_semantic_regressions.py -q`: 14 passed.
- `uv run memco verify-current-status --project-root . --pytest-passed 632`: expected to fail only on release-grade artifact freshness until the live/Postgres JSON artifacts below are regenerated for this exact checkout.
- `var/reports/personal-memory-eval-current.json`: fresh fixture/internal eval proof for this dirty checkout; 840/840 passed.
- `var/reports/release-check-current.json`: fresh quick repo-local release-check proof for this dirty checkout; acceptance 27/27.
- `var/reports/local-artifacts-refresh-current.json`: fresh repo-local refresh summary for this dirty checkout; full suite 632 passed, contract stack 105 passed, release-check acceptance 27/27.
- `var/reports/release-readiness-check-current.json`: historical release-grade artifact from a different checkout; ignore its internal `ok=true` until freshness is current.
- `var/reports/live-operator-smoke-current.json`: historical live-smoke artifact from a different checkout; ignore its internal `ok=true` until freshness is current.
- Independent critic gates are supporting evidence only; do not use critic names as a substitute for validating the current artifacts.

Supporting legacy smoke evidence:

- `var/reports/manual-p0-smoke-current.json`: ok=true, 19/19 manual P0 smoke checks. This is an ad-hoc legacy artifact without `artifact_context`; do not use it as freshness-gated checkout proof.

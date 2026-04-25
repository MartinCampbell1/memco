from __future__ import annotations

from pathlib import Path
import json
import subprocess


REPO_ROOT = Path(__file__).resolve().parents[1]


def _read(relative_path: str) -> str:
    return (REPO_ROOT / relative_path).read_text(encoding="utf-8")


def test_local_reproduction_runbook_documents_realistic_eval_and_live_split():
    runbook = _read("docs/LOCAL_REPRODUCTION.md")

    assert "uv run memco doctor --project-root ." in runbook
    assert "uv run memco eval personal-memory" in runbook
    assert "--fixture-ok" in runbook
    assert "--include-realistic-eval" in runbook
    assert "fixture_only: true" in runbook
    assert "release_eligible: false" in runbook
    assert "MEMCO_LLM_BASE_URL" in runbook
    assert "MEMCO_POSTGRES_DATABASE_URL='postgresql://user:password@127.0.0.1:5432/postgres'" in runbook
    assert "source .env" in runbook
    assert "memco_local" not in _read(".env.example")
    assert "uv run memco person-upsert" in runbook
    assert "MEMCO_RUN_LIVE_SMOKE=1 uv run memco release-readiness-check" in runbook
    assert "--require-live-provider" in runbook
    assert "--require-postgres" in runbook
    assert "Fixture checks may use sqlite and mock/deterministic providers" in runbook
    assert "release claims require the configured Postgres runtime plus live smoke" in runbook


def test_readme_uses_current_contract_language():
    readme = _read("README.md")

    assert "docs/CURRENT_STATUS.md" in readme
    assert "docs/PRIVATE_SINGLE_USER_CONTRACT.md" in readme
    assert "docs/PDF_PARITY_GAPS.md" in readme
    assert "docs/synthius_mem_execution_brief.md" in readme
    assert "docs/2026-04-22_memco_contract_decision.md" in readme
    assert "docs/2026-04-22_memco_original_brief_track_decision.md" in readme
    assert "Older repo-local status snapshots and release closures are historical evidence" in readme
    assert "strict original-brief readiness" in readme
    assert "local, private, operator-controlled, review-gated persona-memory system" in readme
    assert "universal memory substrate or fully autonomous production memory" in readme
    assert "uv run memco release-readiness-check" in readme
    assert "uv run memco release-check" in readme
    assert "--project-root /absolute/path/to/memco" in readme
    assert "--output /absolute/path/to/release-check.json" in readme
    assert "var/reports/release-check-current.json" in readme
    assert "var/reports/release-check-postgres-current.json" in readme
    assert "uv run memco strict-release-check" in readme
    assert "var/reports/strict-release-check-current.json" in readme
    assert "var/reports/benchmark-current.json" in readme
    assert "var/reports/live-operator-smoke-current.json" in readme
    assert "var/reports/repo-local-status-current.json" in readme
    assert "var/reports/change-groups-current.json" in readme
    assert "var/reports/local-artifacts-refresh-current.json" in readme
    assert "var/reports/local-artifacts-refresh-postgres-current.json" in readme
    assert "uv run memco local-artifacts-refresh --project-root /Users/martin/memco" in readme
    assert "--output /absolute/path/to/local-artifacts-refresh.json" in readme
    assert "uv run memco backup runbook --root \"$ROOT\"" in readme
    assert "uv run memco backup export --mode audit" in readme
    assert "uv run memco backup verify var/backups/memco-audit-export.json" in readme
    assert "uv run memco backup restore-dry-run var/backups/memco-full-backup.json.enc" in readme
    backup_runbook = _read("docs/BACKUP_RESTORE_RUNBOOK.md")
    assert "sqlite3 var/db/memco.db \".backup 'var/backups/memco-sqlite.backup'\"" in backup_runbook
    assert "pg_dump \"$MEMCO_POSTGRES_DATABASE_URL\" --format=custom --file var/backups/memco-postgres.dump" in backup_runbook
    assert "pg_restore --clean --if-exists --no-owner" in backup_runbook
    assert "PRAGMA integrity_check" in backup_runbook
    assert "Full encrypted exports are the restore-dry-run path" in readme
    assert "MEMCO_RUN_LIVE_SMOKE=1" in readme
    assert "fail-closed on incomplete live-provider config" in readme
    assert "runtime_policy.ok = false" in readme
    assert "live provider credentials injected into the local operator shell" in readme
    assert "private release claim requires a fresh `release-readiness-check` artifact with live smoke" in readme
    assert "local private operator-controlled release = GO" not in readme
    assert "uv run memco ingest-pipeline /absolute/path/to/conversation.json" in readme
    assert "/v1/ingest/pipeline" in readme
    assert "HTTP API routes require both the shared API token and an `actor` payload" in readme
    assert "X-Memco-Token: replace-with-local-token" in readme
    assert '"actor": {' in readme
    assert '"actor_id": "dev-owner"' in readme
    assert '"auth_token": "from local ignored var/config/settings.yaml actor_policies"' in readme
    assert "conversation-import --latest-source" in readme
    assert "candidate-extract --latest-conversation" in readme
    assert "candidate-publish --latest-candidate" in readme
    assert "fact-operations --latest-target-fact" in readme
    assert "fact-rollback --latest-operation" in readme
    assert "conversation-speaker-resolve SPEAKER_KEY --latest-conversation --person-slug" in readme
    assert "review-resolve approved --latest-review --person-slug alice" in readme
    assert "--publish --reason \"resolved review path\"" in readme
    assert "retrieval-log-list --person-slug alice" in readme
    assert "--detail-policy core_only" in readme
    assert "--detail-policy exhaustive" in readme
    assert "`core_only`" in readme
    assert "`balanced`" in readme
    assert "`exhaustive`" in readme
    assert "/v1/persona/export" in readme
    assert "strict full-brief" not in readme
    assert "fully brief-complete" not in readme
    assert "fully autonomous production memory" in readme


def test_current_docs_entrypoints_separate_status_contract_gaps_and_reproduction():
    current = _read("docs/CURRENT_STATUS.md")
    contract = _read("docs/PRIVATE_SINGLE_USER_CONTRACT.md")
    gaps = _read("docs/PDF_PARITY_GAPS.md")
    local = _read("docs/LOCAL_REPRODUCTION.md")

    assert "Current verdict: P0 semantic remediation is green" in current
    assert "Release-grade GO still requires refreshing the live/Postgres artifacts" in current
    assert "Do not derive this verdict from historical documents." in current
    assert "PRIVATE_SINGLE_USER_CONTRACT.md" in current
    assert "PDF_PARITY_GAPS.md" in current
    assert "LOCAL_REPRODUCTION.md" in current
    assert "P0.7: `memco verify-current-status`" in current
    assert "Selected P1: preference evolution queries" in current
    assert "Selected P1: experiences now include normalized `event_type`/`salience`" in current
    assert "`build-life-timeline` CLI" in current
    assert "Selected P1: social-circle acceptance queries" in current
    assert "Selected P1: work outcome/collaborator acceptance queries" in current
    assert "Selected P1: planner private mode now runs deterministic planning first" in current
    assert "schema/domain-validated and fail-closed when selected" in current
    assert "Selected P1: `memco eval personal-memory` now includes a P1.8 private eval target report" in current
    assert "the fixture/private target counts and thresholds pass for the internal 840-case suite" in current
    assert "not paper-equivalent" in current
    assert "Selected P1: answer guardrails reject prompt-injection attempts" in current
    assert "Selected P1: psychometrics remain explicit opt-in" in current
    assert "do not answer personality questions from one low-confidence signal" in current
    assert "Selected P2: structured parser messages now carry source document" in current
    assert "Selected P2: Markdown journal imports now create heading-based source segments" in current
    assert "inline note imports now create `inline_note` source segments" in current
    assert "file/origin/character locator metadata" in current
    assert "Selected P2: `memco eval personal-memory` now includes a P2.1 external benchmark report" in current
    assert "public/external LoCoMO as `not_run`" in current
    assert "`ok_for_pdf_score_claim=false`" in current
    assert "Selected P2: `memco eval personal-memory` now includes an internal synthetic long-corpus stress smoke" in current
    assert "full P2.3 `ok_for_full_p2_3_claim=false` until 50k/500k-message and mixed-source stress" in current
    assert "not a paper-equivalent benchmark claim" in current
    assert "Selected P2: existing token/latency accounting remains covered" in current
    assert "fail-closes missing token/latency fields" in current
    assert "The personal-memory eval artifact also includes `long_corpus_stress`" in local
    assert "false-positive retrieval checks, and refusal-quality probes" in local
    assert "`p2_3_target_report` keeps full P2.3 `ok_for_full_p2_3_claim=false`" in local
    assert "`p2_1_external_benchmark_report`" in local
    assert "public/external LoCoMO remains `not_run`" in local
    assert "`uv run pytest -q`: 632 passed." in current
    assert "`uv run pytest tests/test_private_agent_semantic_regressions.py -q`: 14 passed." in current
    assert "fresh fixture/internal eval proof for this dirty checkout; 840/840 passed" in current
    assert "fresh quick repo-local release-check proof for this dirty checkout; acceptance 27/27" in current
    assert (
        "fresh repo-local refresh summary for this dirty checkout; "
        "full suite 632 passed, contract stack 105 passed, release-check acceptance 27/27"
    ) in current
    assert "expected to fail only on release-grade artifact freshness" in current
    assert "historical release-grade artifact from a different checkout; ignore its internal `ok=true`" in current
    assert "historical live-smoke artifact from a different checkout; ignore its internal `ok=true`" in current
    assert "manual P0 smoke" in current

    assert "Status: current repo-local contract." in contract
    assert "one private technical owner/operator" in contract
    assert "fully autonomous memory mutation without review gates" in contract
    assert "Release claims must be based on fresh local verification" in contract

    assert "Status: current reference-track gap list." in gaps
    assert "not strict PDF/original-brief complete" in gaps
    assert "LoCoMo-like evaluation is an internal gate" in gaps
    assert "Docker Compose remains a strict original-brief mismatch" in gaps

    assert "# Memco Local Reproduction" in local
    assert "uv run pytest tests/test_private_agent_semantic_regressions.py -q" in local
    assert "uv run memco build-life-timeline alice --root \"$MEMCO_ROOT\"" in local
    assert "uv run memco verify-current-status --project-root . --pytest-passed <fresh-pytest-passed-count>" in local


def test_historical_docs_do_not_redirect_current_status_to_release_closure():
    stale_phrases = [
        "Current verdict lives in docs/2026-04-24_memco_release_closure.md",
        "Current release verdict lives in `docs/2026-04-24_memco_release_closure.md`",
        "use release closure for current status",
        "current release closure records",
        "For the current remediated private-release verdict, read `docs/2026-04-24_memco_release_closure.md` first.",
        "For the current remediated private-release verdict, use `docs/2026-04-24_memco_release_closure.md`.",
        "For the current remediated private single-user verdict, use `docs/2026-04-24_memco_release_closure.md`.",
        "without rechecking against release closure",
        "Old plans/audits point to the release closure",
        "Status: current private release closure",
        "For the current private release state, use the release closure document",
        "The current private release closure records",
    ]
    historical_paths = [
        "dorabotka.md",
        "docs/agent_memory_go_live_plan.md",
        "docs/programmer_agent_no_shortcuts_release_plan.md",
        "docs/2026-04-22_memco_repo_local_status_snapshot.md",
        "docs/2026-04-24_memco_release_remediation_plan.md",
        "docs/2026-04-24_memco_docs_status_map.md",
        "docs/2026-04-24_memco_release_closure.md",
        "docs/2026-04-24_memco_audit_package_index.md",
        "docs/2026-04-24_memco_final_release_audit.md",
        "docs/2026-04-24_memco_final_release_audit_ru.md",
        "docs/2026-04-24_memco_audit_evidence_appendix.md",
        "docs/2026-04-24_memco_blocker_ticket_pack.md",
        "docs/2026-04-24_memco_contract_compliance_matrix.md",
        "docs/2026-04-24_memco_audit_package_integrity.md",
        "docs/2026-04-24_memco_privacy_secret_scan.md",
    ]
    for relative_path in historical_paths:
        doc = _read(relative_path)
        for phrase in stale_phrases:
            assert phrase not in doc


def test_implementation_notes_use_original_brief_language():
    notes = _read("IMPLEMENTATION_NOTES.md")

    assert "Confirmed Deviations From The Original Brief" in notes
    assert "strict original-brief convergence track" in notes
    assert "strict original-brief acceptance/reporting closure" in notes
    assert "docs/2026-04-22_memco_original_brief_track_decision.md" in notes
    assert "The shipped runtime now defaults to the `openai-compatible` provider path." in notes
    assert "The `mock` provider remains available only as an explicit fixture/test fallback" in notes
    assert "Confirmed Deviations From The Full Brief" not in notes


def test_release_gate_is_active_repo_local_gate_with_reference_pointer():
    gate = _read("docs/2026-04-21_memco_release_readiness_gate.md")

    assert "Status: active current repo-local release gate" in gate
    assert "see docs/CURRENT_STATUS.md for the current status entrypoint" in gate
    assert "see docs/2026-04-24_memco_final_release_audit.md for the latest audit verdict" not in gate
    assert "local/private/operator-controlled/review-gated release scope" in gate
    assert "uv run memco release-readiness-check" in gate
    assert "docs/synthius_mem_execution_brief.md" in gate
    assert "2026-04-22_memco_original_brief_status.md" in gate
    assert "2026-04-22_memco_repo_local_status_snapshot.md" in gate
    assert "uv run memco release-check" in gate
    assert "--project-root /absolute/path/to/memco" in gate
    assert "--output /absolute/path/to/release-check.json" in gate
    assert "memco release-check" in gate
    assert "var/reports/release-check-current.json" in gate
    assert "var/reports/release-check-postgres-current.json" in gate
    assert "uv run memco strict-release-check" in gate
    assert "var/reports/strict-release-check-current.json" in gate
    assert "var/reports/benchmark-current.json" in gate
    assert "var/reports/live-operator-smoke-current.json" in gate
    assert "Quick contract-facing regression stack:" in gate
    assert "tests/test_release_check.py" in gate
    assert "tests/test_llm_provider.py" in gate
    assert "uv run memco local-artifacts-refresh --project-root /Users/martin/memco" in gate
    assert "var/reports/local-artifacts-refresh-current.json" in gate
    assert "var/reports/local-artifacts-refresh-postgres-current.json" in gate
    assert "MEMCO_RUN_LIVE_SMOKE=1" in gate
    assert "release-readiness-check --postgres-database-url" in gate
    assert "The runtime policy is intentionally fail-closed." in gate
    assert "release-check` now returns `ok: false`" in gate
    assert "openai-compatible provider is missing api_key" in gate
    assert "MEMCO_LLM_BASE_URL='http://127.0.0.1:2455/v1'" in gate
    assert "missing creds now fail closed by design" in gate
    assert "## Strict Original Brief Reference Track" in gate
    assert "## Strict Original Execution-Brief Readiness" not in gate


def test_private_release_gate_points_to_repo_local_status_snapshot():
    gate = _read("docs/2026-04-21_memco_private_release_gate.md")

    assert "2026-04-22_memco_repo_local_status_snapshot.md" in gate


def test_private_pilot_runbook_covers_required_agent_memory_sequence():
    readme = _read("README.md")
    runbook = _read("docs/PRIVATE_PILOT_RUNBOOK.md")

    assert "docs/PRIVATE_PILOT_RUNBOOK.md" in readme
    assert "Status: active runbook for private single-user agent-memory pilots." in runbook
    assert "uv run memco eval personal-memory --goldens eval/personal_memory_goldens --output var/reports/personal-memory-eval-current.json" in runbook
    assert "Start with synthetic data." in runbook
    assert "Run extraction with manual review." in runbook
    assert "Publish only reviewed facts." in runbook
    assert "Use agents in retrieval-only mode first." in runbook
    assert "Log all unsupported claims." in runbook
    assert "Run a weekly audit of wrong or low-confidence facts." in runbook
    assert "Enable automatic memory injection only after 2-3 clean weeks." in runbook
    assert "retrieve` or `/v1/retrieve`" in runbook
    assert "They must not automatically inject memories into prompts" in runbook
    assert "retrieval-log-list --person-slug alice" in runbook
    assert "no cross-person contamination" in runbook
    assert "no unsupported premise answered as fact" in runbook


def test_execution_brief_defines_repo_local_precedence():
    brief = _read("docs/synthius_mem_execution_brief.md")

    assert "Status: current repo-local iteration scope" in brief
    assert "authoritative current iteration scope" in brief
    assert "honest local private operator-controlled review-gated single-user release" in brief
    assert "release-grade proof through canonical Postgres, operator-readiness, and live operator smoke" in brief
    assert "The original brief remains the architecture/reference document" in brief
    assert "This repo-local brief does not require Docker Compose" in brief
    assert "strict original-brief completion: still a separate question" in brief


def test_postgres_without_docker_guide_mentions_integrated_release_check():
    guide = _read("docs/2026-04-22_postgres_without_docker.md")

    assert "release-check --project-root /Users/martin/memco --postgres-database-url" in guide
    assert "var/reports/release-check-postgres-current.json" in guide
    assert "strict-release-check --project-root /Users/martin/memco --postgres-database-url" in guide
    assert "var/reports/strict-release-check-current.json" in guide
    assert "var/reports/benchmark-current.json" in guide
    assert "var/reports/live-operator-smoke-current.json" in guide
    assert "MEMCO_BACKUP_PATH" in guide


def test_local_operator_artifacts_are_gitignored_but_tracked_status_snapshot_is_not():
    ignored = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "check-ignore", "-v", "HANDOFF_NEXT_AGENT.md", "plan.md", "table.md", ".omc/"],
        check=False,
        capture_output=True,
        text=True,
    )
    tracked = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "check-ignore", "-v", "docs/2026-04-22_memco_repo_local_status_snapshot.md"],
        check=False,
        capture_output=True,
        text=True,
    )

    assert ignored.returncode == 0
    assert ".gitignore" in ignored.stdout
    assert "HANDOFF_NEXT_AGENT.md" in ignored.stdout
    assert "plan.md" in ignored.stdout
    assert "table.md" in ignored.stdout
    assert ".omc/" in ignored.stdout
    assert tracked.returncode == 1
    assert tracked.stdout == ""


def test_ci_reproducibility_gate_uses_lockfile_matrix_and_pip_check():
    ci = _read(".github/workflows/ci.yml")
    candidates_route = _read("src/memco/api/routes/candidates.py")
    review_route = _read("src/memco/api/routes/review.py")
    deps = _read("src/memco/api/deps.py")

    assert 'python-version: ["3.11", "3.12", "3.13"]' in ci
    assert "uv sync --frozen --extra dev --extra parsers" in ci
    assert "uv pip check" in ci
    assert "HTTP_422_UNPROCESSABLE_CONTENT" not in candidates_route
    assert "HTTP_422_UNPROCESSABLE_CONTENT" not in review_route
    assert "HTTP_422_UNPROCESSABLE_CONTENT" not in deps
    assert "HTTP_422_UNPROCESSABLE_ENTITY" not in candidates_route
    assert "HTTP_422_UNPROCESSABLE_ENTITY" not in review_route
    assert "HTTP_422_UNPROCESSABLE_ENTITY" not in deps
    assert "status_code=422" in candidates_route
    assert "status_code=422" in review_route
    assert "status_code=422" in deps


def test_current_contract_includes_messenger_parsers():
    readme = _read("README.md")
    notes = _read("IMPLEMENTATION_NOTES.md")
    brief = _read("docs/synthius_mem_execution_brief.md")

    assert (
        "implemented and supported now: `text`, `markdown`, `chat`, `json`, `csv`, `email`, `pdf`, `html`, `whatsapp`, `telegram`"
        in readme
    )
    assert "WhatsApp and Telegram export parsers are part of the current repo-local ingestion contract" in readme
    assert "`WhatsApp` and `Telegram` parser support is implemented for common export shapes" in notes
    assert "supported now: `text`, `markdown`, `chat`, `json`, `csv`, `email`, `pdf`, `html`, `whatsapp`, `telegram`" in brief


def test_contract_decisions_define_active_and_reference_tracks():
    contract_decision = _read("docs/2026-04-22_memco_contract_decision.md")
    original_track = _read("docs/2026-04-22_memco_original_brief_track_decision.md")

    assert "Status: accepted for current repo-local work" in contract_decision
    assert "the target contract is" in contract_decision
    assert "[synthius_mem_execution_brief.md]" in contract_decision
    assert "2026-04-22_memco_repo_local_status_snapshot.md" in contract_decision
    assert "reference/backlog-only track" in contract_decision

    assert "Status: accepted for current repo-local release management" in original_track
    assert "reference/backlog-only track" in original_track
    assert "not an active release contract for current repo-local work" in original_track
    assert "release claims should be made against the repo-local execution brief" in original_track


def test_original_brief_status_is_separate_reference_track():
    status_doc = _read("docs/2026-04-22_memco_original_brief_status.md")

    assert "Status: reference-track status note" in status_doc
    assert "It is not the active repo-local release gate." in status_doc
    assert "Current status: `NO-GO`" in status_doc
    assert "2026-04-22_memco_repo_local_status_snapshot.md" in status_doc


def test_repo_local_status_snapshot_tracks_current_contract_split():
    snapshot = _read("docs/2026-04-22_memco_repo_local_status_snapshot.md")

    assert "Active repo-local contract status: `GO`" in snapshot
    assert "Scope: local/private/operator-controlled/review-gated persona memory." in snapshot
    assert "release artifacts include generation timestamp, runtime mode, config source, env override state, live-smoke state, and checkout/config freshness context" in snapshot
    assert "release-readiness-check --project-root /Users/martin/memco" in snapshot
    assert "strict original brief: `NO-GO`" in snapshot
    assert "Contract-facing regression stack:" in snapshot
    assert "87 passed" in snapshot
    assert "plain checkout shell without injected live provider creds" in snapshot
    assert "`uv run memco release-check --project-root /Users/martin/memco` -> `ok: false`" in snapshot
    assert "`runtime_policy.reason` -> `openai-compatible provider is missing api_key`" in snapshot
    assert "green operator path with live creds injected into the local shell" in snapshot
    assert "pytest gate inside release-check -> `52 passed`" in snapshot
    assert "http://127.0.0.1:2455/v1" in snapshot
    assert "var/reports/release-check-current.json" in snapshot
    assert "var/reports/release-check-postgres-current.json" in snapshot
    assert "var/reports/live-operator-smoke-current.json" in snapshot
    assert "var/reports/repo-local-status-current.json" in snapshot
    assert "mirrors the current branch, remote, contract split, and latest validation counts" in snapshot
    assert "var/reports/change-groups-current.json" in snapshot
    assert "var/reports/local-artifacts-refresh-current.json" in snapshot
    assert "var/reports/local-artifacts-refresh-postgres-current.json" in snapshot
    assert "HANDOFF_NEXT_AGENT.md` is intentionally local and ignored by git" in snapshot
    assert "## First Commands" in snapshot
    assert "uv run memco release-check --project-root /Users/martin/memco" in snapshot
    assert "uv run memco local-artifacts-refresh --project-root /Users/martin/memco" in snapshot


def test_full_fix_plan_uses_current_contract_resolution():
    plan = _read("docs/plans/2026-04-21_memco_full_fix_plan.md")

    assert "Primary contract document: [../synthius_mem_execution_brief.md]" in plan
    assert "done for current repo-local release management" in plan
    assert "reference/backlog-only rather than an active release contract" in plan
    assert "final decision on whether the repo should target" not in plan


def test_repo_local_status_snapshot_captures_handoff_grade_context():
    snapshot = _read("docs/2026-04-22_memco_repo_local_status_snapshot.md")

    assert "Updated plan-of-record" not in snapshot
    assert "Active repo-local contract status: `GO`" in snapshot
    assert "strict original brief: `NO-GO`" in snapshot
    assert "var/reports/release-check-current.json" in snapshot
    assert "var/reports/release-check-postgres-current.json" in snapshot
    assert "fact_ids" in snapshot
    assert "evidence_ids" in snapshot
    assert "operator safety now requires" in snapshot
    assert "Inject live provider env before expecting `release-check` to return `ok: true`." in snapshot


def test_historical_release_plans_are_not_current_verdicts():
    historical_docs = [
        "docs/2026-04-24_memco_release_closure.md",
        "docs/2026-04-24_memco_docs_status_map.md",
        "docs/2026-04-21_memco_blocker_matrix.md",
        "docs/2026-04-21_memco_executive_verdict_ru.md",
        "docs/2026-04-21_memco_grounded_audit.md",
        "docs/2026-04-22_docker_engine_blocker.md",
        "docs/plans/2026-04-21_memco_full_fix_plan.md",
        "docs/plans/2026-04-21_memco_release_gap_remediation.md",
        "docs/2026-04-24_memco_final_release_audit.md",
        "docs/2026-04-24_memco_final_release_audit_ru.md",
        "docs/2026-04-24_memco_audit_evidence_appendix.md",
        "docs/agent_memory_go_live_plan.md",
        "docs/programmer_agent_no_shortcuts_release_plan.md",
        "dorabotka.md",
        "docs/2026-04-22_memco_repo_local_status_snapshot.md",
        "docs/2026-04-21_memco_single_user_operator_check.md",
    ]
    for relative_path in historical_docs:
        doc = _read(relative_path)
        assert doc.startswith("Historical document. Not current verdict.\nCurrent verdict: see docs/CURRENT_STATUS.md")
        assert "Not current verdict" in doc
        assert "docs/CURRENT_STATUS.md" in doc

    gate = _read("docs/2026-04-21_memco_release_readiness_gate.md")
    assert "Status note: active gate definition, not current checkout proof by itself." in gate
    assert "fresh `release-readiness-check` artifact with live smoke" in gate


def test_release_closure_is_historical_private_go_evidence():
    closure = _read("docs/2026-04-24_memco_release_closure.md")
    status_map = _read("docs/2026-04-24_memco_docs_status_map.md")

    assert closure.startswith("Historical document. Not current verdict.\nCurrent verdict: see docs/CURRENT_STATUS.md")
    assert "Status: historical dated private release closure, not current checkout verdict" in closure
    assert "Final private Hermes/API-backed verdict: `GO`" in closure
    assert "single-user, local/private/operator-controlled/review-gated" in closure
    assert "Strict original brief verdict: `NO-GO/reference-track`" in closure
    assert "`uv run pytest -q` -> `441 passed`" in closure
    assert "`operator-preflight` -> `ok: true`" in closure
    assert "`release-readiness-check` -> `ok: true`" in closure
    assert "`status_source: config-only`" in closure
    assert "`env_overrides.used: false`" in closure
    assert "`live_operator_smoke.ok: true`" in closure
    assert "`live_operator_smoke.artifact_context.checkout.dirty: false`" in closure
    assert "`live_operator_smoke.artifact_context.checkout.git_head` is recorded in the current artifact" in closure
    assert "`current_for_checkout_config: True`" in closure
    assert "No provider key is recorded in tracked source/docs." in closure
    assert "Local runtime config permissions are owner-only: `var/config/` is `0700`, `settings.yaml` is `0600`." in closure

    assert "docs/2026-04-24_memco_release_closure.md" in status_map
    assert "Historical private verdict in that dated closure" in status_map
    assert "Final private Hermes/API-backed verdict: `GO`" in status_map


def test_docs_status_map_reflects_post_remediation_state():
    status_map = _read("docs/2026-04-24_memco_docs_status_map.md")
    matrix = _read("docs/2026-04-24_memco_contract_compliance_matrix.md")
    blocker_pack = _read("docs/2026-04-24_memco_blocker_ticket_pack.md")
    remediation_plan = _read("docs/2026-04-24_memco_release_remediation_plan.md")

    assert "Rule: for the current checkout, start with `docs/CURRENT_STATUS.md`." in status_map
    assert "Resolved Post-Remediation State" in status_map
    assert "root `IMPLEMENTATION_NOTES.md` is restored" in status_map
    assert "README HTTP examples include required actor payloads" in status_map
    assert "`release-readiness-check-current.json` and `live-operator-smoke-current.json` are proof only" in status_map
    assert "hardcoded pass counts, clean/dirty state, or artifact names from historical runs" in status_map
    assert "`uv run pytest -q` passed with `441 passed`" not in status_map
    assert "read the exact current git head from the artifact" in status_map
    assert "`live-operator-smoke-current.json` must have `api_queries.ok=true`" in status_map
    assert "root IMPLEMENTATION_NOTES.md is deleted" not in status_map
    assert "Full suite is red" not in status_map
    assert "Current Document-Level Fixes Still Needed" not in status_map
    assert "Start with `docs/CURRENT_STATUS.md` for the current verdict." in status_map

    for doc in (matrix, blocker_pack, remediation_plan):
        assert doc.startswith("Historical document. Not current verdict.\nCurrent verdict: see docs/CURRENT_STATUS.md")
        assert "historical pre-remediation" in doc
        assert "Not current verdict" in doc
        assert "docs/CURRENT_STATUS.md" in doc


def test_audit_package_entrypoints_are_marked_historical_after_remediation():
    index = _read("docs/2026-04-24_memco_audit_package_index.md")
    integrity = _read("docs/2026-04-24_memco_audit_package_integrity.md")
    privacy = _read("docs/2026-04-24_memco_privacy_secret_scan.md")
    manifest = json.loads(_read("docs/2026-04-24_memco_audit_package_manifest.json"))

    for doc in (index, integrity, privacy):
        assert doc.startswith("Historical document. Not current verdict.\nCurrent verdict: see docs/CURRENT_STATUS.md")
        assert "historical pre-remediation" in doc
        assert "Not current verdict" in doc
        assert "docs/CURRENT_STATUS.md" in doc

    assert manifest["verdict"]["summary"] == "historical pre-remediation NO-GO baseline"
    assert manifest["current_status"] == "docs/CURRENT_STATUS.md"
    assert manifest["historical_release_closure"] == "docs/2026-04-24_memco_release_closure.md"
    assert manifest["current_private_verdict"] == "see docs/CURRENT_STATUS.md"
    assert manifest["entrypoints"]["read_first"] == "docs/CURRENT_STATUS.md"


def test_local_release_reports_if_present_use_scoped_release_language():
    reports_dir = REPO_ROOT / "var" / "reports"
    required = [
        reports_dir / "release-notes-current.md",
        reports_dir / "release-notes-current.json",
        reports_dir / "final-tz-closure-current.md",
        reports_dir / "final-tz-closure-current.json",
        reports_dir / "reports-index-current.md",
        reports_dir / "reports-index-current.json",
    ]
    if not all(path.exists() for path in required):
        return

    release_notes = (reports_dir / "release-notes-current.md").read_text(encoding="utf-8")
    final_closure = (reports_dir / "final-tz-closure-current.md").read_text(encoding="utf-8")
    reports_index = (reports_dir / "reports-index-current.md").read_text(encoding="utf-8")
    release_notes_json = json.loads((reports_dir / "release-notes-current.json").read_text(encoding="utf-8"))
    final_closure_json = json.loads((reports_dir / "final-tz-closure-current.json").read_text(encoding="utf-8"))
    reports_index_json = json.loads((reports_dir / "reports-index-current.json").read_text(encoding="utf-8"))

    for text in (release_notes, final_closure, reports_index):
        assert "local/private/operator-controlled/review-gated" in text
        assert "release-readiness-check" in text
        assert "universal memory substrate" in text

    for payload in (release_notes_json, final_closure_json, reports_index_json):
        assert payload["release_scope"] == "local_private_operator_controlled_review_gated"
        assert "universal memory substrate" in payload["scope_caveat"]
        assert "release-readiness-check" in json.dumps(payload, ensure_ascii=False)

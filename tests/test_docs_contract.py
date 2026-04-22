from __future__ import annotations

from pathlib import Path
import subprocess


REPO_ROOT = Path(__file__).resolve().parents[1]


def _read(relative_path: str) -> str:
    return (REPO_ROOT / relative_path).read_text(encoding="utf-8")


def test_readme_uses_current_contract_language():
    readme = _read("README.md")

    assert "docs/synthius_mem_execution_brief.md" in readme
    assert "docs/2026-04-22_memco_contract_decision.md" in readme
    assert "docs/2026-04-22_memco_original_brief_track_decision.md" in readme
    assert "docs/2026-04-22_memco_repo_local_status_snapshot.md" in readme
    assert "strict original-brief readiness" in readme
    assert "uv run memco release-check" in readme
    assert "--project-root /absolute/path/to/memco" in readme
    assert "--output /absolute/path/to/release-check.json" in readme
    assert "var/reports/release-check-current.json" in readme
    assert "var/reports/release-check-postgres-current.json" in readme
    assert "var/reports/repo-local-status-current.json" in readme
    assert "var/reports/change-groups-current.json" in readme
    assert "var/reports/local-artifacts-refresh-current.json" in readme
    assert "var/reports/local-artifacts-refresh-postgres-current.json" in readme
    assert "uv run memco local-artifacts-refresh --project-root /Users/martin/memco" in readme
    assert "--output /absolute/path/to/local-artifacts-refresh.json" in readme
    assert "uv run memco ingest-pipeline /absolute/path/to/conversation.json" in readme
    assert "/v1/ingest/pipeline" in readme
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
    assert "docs/synthius_mem_execution_brief.md" in gate
    assert "2026-04-22_memco_original_brief_status.md" in gate
    assert "2026-04-22_memco_repo_local_status_snapshot.md" in gate
    assert "uv run memco release-check" in gate
    assert "--project-root /absolute/path/to/memco" in gate
    assert "--output /absolute/path/to/release-check.json" in gate
    assert "memco release-check" in gate
    assert "var/reports/release-check-current.json" in gate
    assert "var/reports/release-check-postgres-current.json" in gate
    assert "Quick contract-facing regression stack:" in gate
    assert "tests/test_release_check.py" in gate
    assert "tests/test_llm_provider.py" in gate
    assert "uv run memco local-artifacts-refresh --project-root /Users/martin/memco" in gate
    assert "var/reports/local-artifacts-refresh-current.json" in gate
    assert "var/reports/local-artifacts-refresh-postgres-current.json" in gate
    assert "## Strict Original Brief Reference Track" in gate
    assert "## Strict Original Execution-Brief Readiness" not in gate


def test_private_release_gate_points_to_repo_local_status_snapshot():
    gate = _read("docs/2026-04-21_memco_private_release_gate.md")

    assert "2026-04-22_memco_repo_local_status_snapshot.md" in gate


def test_execution_brief_defines_repo_local_precedence():
    brief = _read("docs/synthius_mem_execution_brief.md")

    assert "Status: current repo-local iteration scope" in brief
    assert "authoritative current iteration scope" in brief
    assert "The original brief remains the architecture/reference document" in brief
    assert "This repo-local brief does not require Docker Compose" in brief
    assert "strict original-brief completion: still a separate question" in brief


def test_postgres_without_docker_guide_mentions_integrated_release_check():
    guide = _read("docs/2026-04-22_postgres_without_docker.md")

    assert "release-check --project-root /Users/martin/memco --postgres-database-url" in guide
    assert "var/reports/release-check-postgres-current.json" in guide


def test_local_operator_artifacts_are_gitignored_but_tracked_status_snapshot_is_not():
    ignored = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "check-ignore", "-v", "HANDOFF_NEXT_AGENT.md", "plan.md", "table.md"],
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
    assert tracked.returncode == 1
    assert tracked.stdout == ""


def test_current_contract_explicitly_scopes_out_whatsapp_and_telegram():
    readme = _read("README.md")
    notes = _read("IMPLEMENTATION_NOTES.md")
    brief = _read("docs/synthius_mem_execution_brief.md")

    assert "WhatsApp or Telegram export parsers are already part of the current repo-local ingestion contract" in readme
    assert "implemented and supported now: `text`, `markdown`, `chat`, `json`, `csv`, `email`, `pdf`" in readme
    assert "`WhatsApp` / `Telegram` remain roadmap/reference-track parser targets" in readme
    assert "`WhatsApp` and `Telegram` parser support remain roadmap/reference-track items" in notes
    assert "not part of the current repo-local contract: `WhatsApp`, `Telegram`" in brief


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
    assert "strict original brief: `NO-GO`" in snapshot
    assert "Contract-facing regression stack:" in snapshot
    assert "46 passed" in snapshot
    assert "var/reports/release-check-current.json" in snapshot
    assert "var/reports/release-check-postgres-current.json" in snapshot
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

from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def _read(relative_path: str) -> str:
    return (REPO_ROOT / relative_path).read_text(encoding="utf-8")


def test_readme_uses_current_contract_language():
    readme = _read("README.md")

    assert "docs/synthius_mem_execution_brief.md" in readme
    assert "docs/2026-04-22_memco_contract_decision.md" in readme
    assert "docs/2026-04-22_memco_original_brief_track_decision.md" in readme
    assert "strict original-brief readiness" in readme
    assert "uv run memco release-check" in readme
    assert "--project-root /absolute/path/to/memco" in readme
    assert "--output /absolute/path/to/release-check.json" in readme
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
    assert "strict full-brief" not in readme
    assert "fully brief-complete" not in readme


def test_implementation_notes_use_original_brief_language():
    notes = _read("IMPLEMENTATION_NOTES.md")

    assert "Confirmed Deviations From The Original Brief" in notes
    assert "strict original-brief convergence track" in notes
    assert "strict original-brief acceptance/reporting closure" in notes
    assert "docs/2026-04-22_memco_original_brief_track_decision.md" in notes
    assert "Confirmed Deviations From The Full Brief" not in notes


def test_release_gate_is_active_repo_local_gate_with_reference_pointer():
    gate = _read("docs/2026-04-21_memco_release_readiness_gate.md")

    assert "Status: active current repo-local release gate" in gate
    assert "docs/synthius_mem_execution_brief.md" in gate
    assert "2026-04-22_memco_original_brief_status.md" in gate
    assert "uv run memco release-check" in gate
    assert "--project-root /absolute/path/to/memco" in gate
    assert "--output /absolute/path/to/release-check.json" in gate
    assert "memco release-check" in gate
    assert "## Strict Original Brief Reference Track" in gate
    assert "## Strict Original Execution-Brief Readiness" not in gate


def test_execution_brief_defines_repo_local_precedence():
    brief = _read("docs/synthius_mem_execution_brief.md")

    assert "Status: current repo-local iteration scope" in brief
    assert "authoritative current iteration scope" in brief
    assert "The original brief remains the architecture/reference document" in brief
    assert "This repo-local brief does not require Docker Compose" in brief
    assert "strict original-brief completion: still a separate question" in brief


def test_contract_decisions_define_active_and_reference_tracks():
    contract_decision = _read("docs/2026-04-22_memco_contract_decision.md")
    original_track = _read("docs/2026-04-22_memco_original_brief_track_decision.md")

    assert "Status: accepted for current repo-local work" in contract_decision
    assert "the target contract is" in contract_decision
    assert "[synthius_mem_execution_brief.md]" in contract_decision
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


def test_full_fix_plan_uses_current_contract_resolution():
    plan = _read("docs/plans/2026-04-21_memco_full_fix_plan.md")

    assert "Primary contract document: [../synthius_mem_execution_brief.md]" in plan
    assert "done for current repo-local release management" in plan
    assert "reference/backlog-only rather than an active release contract" in plan
    assert "final decision on whether the repo should target" not in plan

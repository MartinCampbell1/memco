from __future__ import annotations

import json
from pathlib import Path
import re

from click.testing import CliRunner
from typer.main import get_command

from memco.artifact_semantics import evaluate_artifact_freshness
from memco.cli.main import app
from memco.models.retrieval import RetrievalRequest
from memco.services.eval_service import EvalService
from memco.services.planner_service import PlannerService


GOLDENS_DIR = Path("eval/personal_memory_goldens")
LOCOMO_LIKE_MANIFEST = GOLDENS_DIR / EvalService.LOCOMO_LIKE_MANIFEST_NAME
LOCOMO_LIKE_CONVERSATIONS = GOLDENS_DIR / "locomo_like_conversations.json"


def _load_goldens() -> list[dict]:
    cases: list[dict] = []
    for path in sorted(GOLDENS_DIR.glob("*.jsonl")):
        with path.open("r", encoding="utf-8") as handle:
            cases.extend(json.loads(line) for line in handle if line.strip())
    return cases


def test_personal_memory_goldens_cover_required_groups():
    cases = _load_goldens()
    locomo_manifest = json.loads(LOCOMO_LIKE_MANIFEST.read_text(encoding="utf-8"))
    locomo_conversation_payload = json.loads(LOCOMO_LIKE_CONVERSATIONS.read_text(encoding="utf-8"))
    locomo_conversations = locomo_manifest["conversations"]
    locomo_fixture_by_id = {
        conversation["conversation_id"]: conversation
        for conversation in locomo_conversation_payload["conversations"]
    }
    cases_by_conversation: dict[str, list[dict]] = {}
    for item in cases:
        cases_by_conversation.setdefault(item["conversation_id"], []).append(item)
    locomo_coverage = {
        coverage
        for conversation in locomo_conversations
        for coverage in conversation["coverage"]
    }
    counts = {
        group: sum(1 for item in cases if item["group"] == group)
        for group in EvalService.PERSONAL_MEMORY_REQUIRED_COUNTS
    }
    realistic_cases = [
        item for item in cases if str(item["id"]).startswith("realistic_")
    ]
    scenario_counts = {
        scenario: sum(1 for item in realistic_cases if item.get("scenario") == scenario)
        for scenario in {
            "biography",
            "work",
            "experiences",
            "preferences",
            "social",
            "temporal",
            "adversarial",
            "cross_person",
            "update_supersede",
            "speakerless",
            "negation_hypothetical",
        }
    }
    realistic_text = "\n".join(json.dumps(item, ensure_ascii=False).lower() for item in realistic_cases)
    placeholder_re = re.compile(
        r"Realistic [A-Za-z ]+ \d{3}|[a-z]+-value-\d{3}|Work\d{3}|ClientPortal\d{3}|OldCity\d{3}|HypotheticalValue\d{3}"
    )

    assert len(cases) == 680
    assert len({item["id"] for item in cases}) == len(cases)
    assert (GOLDENS_DIR / "realistic_personal_memory_goldens.jsonl").exists()
    assert LOCOMO_LIKE_MANIFEST.exists()
    assert LOCOMO_LIKE_CONVERSATIONS.exists()
    assert locomo_manifest["benchmark_disclaimer"] == "Internal LoCoMo-like personal-memory eval metadata; not paper-equivalent."
    assert locomo_manifest["eventual_target_questions"] == 1000
    assert locomo_manifest["conversations_file"] == LOCOMO_LIKE_CONVERSATIONS.name
    assert len(locomo_conversations) >= 10
    assert len(locomo_fixture_by_id) == len(locomo_conversations)
    assert set(cases_by_conversation) == {
        conversation["conversation_id"]
        for conversation in locomo_conversations
    }
    assert sum(len(items) for items in cases_by_conversation.values()) == len(cases)
    assert all(
        len(locomo_fixture_by_id[conversation["conversation_id"]]["turns"])
        >= locomo_manifest["long_conversation_min_turns"]
        for conversation in locomo_conversations
    )
    assert all(
        len(
            {
                turn["speaker_slug"]
                for turn in locomo_fixture_by_id[conversation["conversation_id"]]["turns"]
            }
        )
        >= 2
        for conversation in locomo_conversations
    )
    assert all(
        set(conversation["person_slugs"])
        == {
            turn["speaker_slug"]
            for turn in locomo_fixture_by_id[conversation["conversation_id"]]["turns"]
        }
        for conversation in locomo_conversations
    )
    assert all(
        set(locomo_fixture_by_id[conversation["conversation_id"]]["linked_case_ids"])
        == {item["id"] for item in cases_by_conversation[conversation["conversation_id"]]}
        for conversation in locomo_conversations
    )
    assert all(
        {item["person_slug"] for item in cases_by_conversation[conversation["conversation_id"]]}
        <= set(conversation["person_slugs"])
        for conversation in locomo_conversations
    )
    assert set(EvalService.PERSONAL_MEMORY_COVERAGE_GROUPS) <= locomo_coverage
    assert {item["group"] for item in realistic_cases} == set(EvalService.PERSONAL_MEMORY_REQUIRED_COUNTS)
    assert len(realistic_cases) == 300
    assert scenario_counts == {
        "biography": 25,
        "work": 25,
        "experiences": 25,
        "preferences": 25,
        "social": 25,
        "temporal": 25,
        "adversarial": 50,
        "cross_person": 25,
        "update_supersede": 25,
        "speakerless": 25,
        "negation_hypothetical": 25,
    }
    for required_phrase in (
        "i do not like sushi.",
        "i might move to paris next year.",
        "berlin",
        "lisbon",
        "maria in porto",
        "bob in berlin",
        "i use python and postgres.",
        "in october 2023 i had a serious accident at the grand canyon.",
        "i worked on project phoenix and launched it in march.",
        "i prefer coffee, but i used to prefer tea.",
    ):
        assert required_phrase in realistic_text
    source_checks = {
        item.get("source_hard_check"): item.get("source_text")
        for item in realistic_cases
        if item.get("source_hard_check")
    }
    assert source_checks == {
        "combined_tools_split": "I use Python and Postgres.",
        "combined_project_temporal": "I worked on Project Phoenix and launched it in March.",
        "experience_accident_temporal": "In October 2023 I had a serious accident at the Grand Canyon.",
        "preference_update_current": "I prefer coffee, but I used to prefer tea.",
        "negated_preference_not_positive": "I do not like sushi.",
        "hypothetical_residence_not_positive": "I might move to Paris next year.",
    }
    assert placeholder_re.search("\n".join(json.dumps(item, ensure_ascii=False) for item in realistic_cases)) is None
    assert counts == {
        **EvalService.PERSONAL_MEMORY_REQUIRED_COUNTS,
        "core_fact": 174,
        "adversarial_false_premise": 125,
        "social_family": 75,
        "temporal": 76,
        "preference": 75,
        "cross_person_contamination": 55,
        "speakerless_note": 55,
        "rollback_update": 45,
    }


def test_personal_memory_planner_does_not_treat_personal_as_son_relation():
    plan = PlannerService().plan(
        RetrievalRequest(
            person_slug="personal-preference-001",
            query="What is Personal Preference 001 preference?",
            domain="preferences",
            category="preference",
        )
    )

    assert all(check.value != "son" for check in plan.claim_checks)


def test_personal_memory_eval_gate_passes_all_cases(settings):
    result = EvalService().run_personal_memory(project_root=settings.root, goldens_dir=GOLDENS_DIR)

    assert result["artifact_type"] == "personal_memory_eval_artifact"
    assert result["release_scope"] == "personal-agent-memory"
    assert result["ok"] is True
    assert result["total"] == 680
    assert result["passed"] == 680
    assert result["failed"] == 0
    assert result["failures"] == []
    assert all(item["ok"] for item in result["policy_checks"].values())
    assert all(item["ok"] for item in result["dataset_count_checks"].values())
    assert result["metrics"]["overall_accuracy"] >= 0.90
    assert result["metrics"]["core_memory_accuracy"] >= 0.95
    assert result["metrics"]["adversarial_robustness"] >= 0.98
    assert result["metrics"]["temporal_accuracy"] >= 0.90
    assert result["metrics"]["cross_person_contamination"] == 0
    assert result["metrics"]["unsupported_premise_answered_as_fact"] == 0
    assert result["metrics"]["evidence_missing_on_supported_answers"] == 0
    assert result["metrics"]["speakerless_owner_fallback_accuracy"] >= 0.95
    assert result["metrics"]["tool_project_retrieval_pass_rate"] >= 0.95
    assert result["metrics"]["experience_event_retrieval_pass_rate"] >= 0.90
    assert result["metrics"]["source_hard_case_failures"] == 0
    assert result["source_hard_checks_total"] == 6
    assert result["source_hard_checks_passed"] == 6
    assert result["memory_evolution_checks"]["ok"] is True
    assert result["memory_evolution_checks"]["failed"] == 0
    assert result["memory_evolution_checks"]["missing_required_checks"] == []
    assert {item["name"] for item in result["memory_evolution_checks"]["checks"]} == {
        "incremental_import_creates_active_fact",
        "same_conversation_reextract_idempotent",
        "same_source_reimport_no_duplicate_active_facts",
        "conflict_update_supersedes_previous_fact",
        "current_query_returns_new_fact",
        "historical_query_returns_superseded_fact",
        "stale_superseded_fact_excluded_from_current",
        "delete_hides_fact_from_retrieval",
        "restore_deleted_fact_retrievable",
        "rollback_restores_previous_active_state",
    }
    assert all(item["passed"] for item in result["memory_evolution_checks"]["checks"])
    assert result["policy_checks"]["memory_evolution_update_fidelity"] == {
        "value": result["memory_evolution_checks"]["passed"],
        "threshold": result["memory_evolution_checks"]["total"],
        "ok": True,
    }
    assert {item["source_hard_check"] for item in result["source_hard_checks"]} == {
        "combined_tools_split",
        "combined_project_temporal",
        "experience_accident_temporal",
        "preference_update_current",
        "negated_preference_not_positive",
        "hypothetical_residence_not_positive",
    }
    assert result["policy_checks"]["tool_project_retrieval_pass_rate"]["ok"] is True
    assert result["policy_checks"]["experience_event_retrieval_pass_rate"]["ok"] is True
    assert result["policy_checks"]["source_hard_case_failures"]["ok"] is True
    assert result["policy_checks"]["overall_accuracy"]["threshold"] == 0.90
    assert result["policy_checks"]["temporal_accuracy"]["threshold"] == 0.90
    assert result["coverage"]["single_hop"]["covered"] is True
    assert result["coverage"]["multi_hop"]["covered"] is True
    assert result["coverage"]["temporal"]["covered"] is True
    assert result["coverage"]["open_inference"]["covered"] is True
    assert result["coverage"]["adversarial_false_premise"]["covered"] is True
    assert result["coverage"]["cross_person"]["covered"] is True
    assert result["dataset_count_checks"]["locomo_like_conversation_count"] == {
        "value": 10,
        "required": 10,
        "ok": True,
    }
    assert result["dataset_count_checks"]["locomo_like_long_conversations"] == {
        "value": 10,
        "required": 10,
        "ok": True,
    }
    assert result["dataset_count_checks"]["locomo_like_persons_per_conversation"]["value"] >= 2
    assert result["dataset_count_checks"]["locomo_like_persons_per_conversation"]["required"] == 2
    assert result["dataset_count_checks"]["locomo_like_persons_per_conversation"]["ok"] is True
    assert result["dataset_count_checks"]["locomo_like_coverage_dimensions"] == {
        "value": [
            "adversarial_false_premise",
            "cross_person",
            "multi_hop",
            "open_inference",
            "single_hop",
            "temporal",
        ],
        "required": [
            "adversarial_false_premise",
            "cross_person",
            "multi_hop",
            "open_inference",
            "single_hop",
            "temporal",
        ],
        "ok": True,
    }
    assert result["dataset_count_checks"]["locomo_like_cases_linked_to_conversations"] == {
        "value": 680,
        "required": 680,
        "ok": True,
    }
    assert result["locomo_like_scope"]["benchmark_disclaimer"] == "Internal LoCoMo-like personal-memory eval; not paper-equivalent."
    assert result["locomo_like_scope"]["current_questions"] == 680
    assert result["locomo_like_scope"]["eventual_target_questions"] == 1000
    assert result["locomo_like_scope"]["conversation_suite"]["ok"] is True
    assert result["locomo_like_scope"]["conversation_suite"]["conversation_count"] == 10
    assert result["locomo_like_scope"]["conversation_suite"]["long_conversation_count"] == 10
    assert result["locomo_like_scope"]["conversation_suite"]["long_conversation_min_turns"] == 50
    assert result["locomo_like_scope"]["conversation_suite"]["min_persons_per_conversation"] >= 2
    assert result["locomo_like_scope"]["conversation_suite"]["all_conversations_have_two_or_more_persons"] is True
    assert result["locomo_like_scope"]["conversation_suite"]["all_turns_have_two_or_more_speakers"] is True
    assert result["locomo_like_scope"]["conversation_suite"]["linked_case_count"] == 680
    assert result["locomo_like_scope"]["conversation_suite"]["total_case_count"] == 680
    assert result["locomo_like_scope"]["conversation_suite"]["all_cases_linked_to_conversations"] is True
    assert result["locomo_like_scope"]["conversation_suite"]["all_fixture_case_links_match"] is True
    assert result["locomo_like_scope"]["conversation_suite"]["all_case_persons_present_in_turns"] is True
    assert result["locomo_like_scope"]["conversation_suite"]["missing_coverage_dimensions"] == []
    assert result["locomo_like_scope"]["private_gate_thresholds"] == {
        "overall_accuracy_min": 0.90,
        "core_memory_accuracy_min": 0.95,
        "adversarial_robustness_min": 0.98,
        "temporal_accuracy_min": 0.90,
        "cross_person_contamination_max": 0,
        "unsupported_premise_answered_as_fact_max": 0,
    }


def test_personal_memory_eval_fails_when_hard_cases_are_mutated(settings, tmp_path):
    mutated_dir = tmp_path / "goldens"
    mutated_dir.mkdir()
    synthetic = GOLDENS_DIR / "synthetic_personal_memory_goldens.jsonl"
    (mutated_dir / synthetic.name).write_text(synthetic.read_text(encoding="utf-8"), encoding="utf-8")
    hard_case_ids = {
        "realistic_work_001",
        "realistic_work_002",
        "realistic_experiences_001",
        "realistic_preference_001",
        "realistic_update_001",
        "realistic_cross_person_001",
        "realistic_negation_hypothetical_001",
        "realistic_negation_hypothetical_002",
    }
    mutated_lines = []
    with (GOLDENS_DIR / "realistic_personal_memory_goldens.jsonl").open("r", encoding="utf-8") as handle:
        for raw_line in handle:
            item = json.loads(raw_line)
            if item["id"] in hard_case_ids:
                if item["expect_refused"]:
                    item["expect_refused"] = False
                else:
                    item["expected_values"] = ["mutated value that is not present"]
            mutated_lines.append(json.dumps(item, ensure_ascii=False, sort_keys=True))
    (mutated_dir / "realistic_personal_memory_goldens.jsonl").write_text("\n".join(mutated_lines) + "\n", encoding="utf-8")

    result = EvalService().run_personal_memory(project_root=settings.root, goldens_dir=mutated_dir)
    failed_ids = {item["id"] for item in result["failures"]}

    assert result["ok"] is False
    assert hard_case_ids <= failed_ids


def test_personal_memory_source_hard_check_rejects_seed_masked_project_source():
    result = EvalService()._personal_source_hard_check(
        {
            "id": "probe_project_seed_masks_source",
            "person_slug": "probe",
            "person_display_name": "Probe",
            "source_hard_check": "combined_project_temporal",
            "source_text": "I ate a banana.",
            "seed_facts": [
                {
                    "domain": "work",
                    "category": "project",
                    "payload": {"project": "Project Phoenix", "temporal_anchor": "March"},
                    "summary": "Probe worked on Project Phoenix and launched it in March.",
                }
            ],
        }
    )

    assert result["passed"] is False
    assert "source_project_phoenix_missing" in result["failures"]
    assert "source_project_temporal_anchor_missing" in result["failures"]
    assert "seed_project_phoenix_missing" not in result["failures"]
    assert "seed_project_temporal_anchor_missing" not in result["failures"]


def test_personal_memory_eval_cli_writes_gate_artifact(tmp_path):
    runner = CliRunner()
    command = get_command(app)
    runtime_root = tmp_path / "personal-memory-runtime"
    output_path = tmp_path / "personal-memory-eval-current.json"

    result = runner.invoke(
        command,
        [
            "eval",
            "personal-memory",
            "--root",
            str(runtime_root),
            "--goldens",
            str(GOLDENS_DIR),
            "--output",
            str(output_path),
        ],
        prog_name="memco",
    )

    assert result.exit_code == 0, result.output
    artifact = json.loads(output_path.read_text(encoding="utf-8"))
    assert artifact["artifact_path"] == str(output_path.resolve())
    assert artifact["ok"] is True
    assert artifact["total"] == 680
    assert artifact["failed"] == 0
    assert artifact["artifact_context"]["freshness"]["status"] == "current_at_generation"
    freshness = evaluate_artifact_freshness(artifact, project_root=Path.cwd().resolve())
    assert freshness["current_for_checkout_config"] is True


def test_personal_memory_eval_root_alias_accepts_realistic_filename(tmp_path):
    runner = CliRunner()
    command = get_command(app)
    runtime_root = tmp_path / "personal-memory-runtime"
    output_path = tmp_path / "personal-memory-eval-current.json"

    result = runner.invoke(
        command,
        [
            "personal-memory-eval",
            "--root",
            str(runtime_root),
            "--goldens",
            "realistic_personal_memory_goldens.jsonl",
            "--output",
            str(output_path),
        ],
        prog_name="memco",
    )

    assert result.exit_code == 0, result.output
    artifact = json.loads(output_path.read_text(encoding="utf-8"))
    assert artifact["artifact_path"] == str(output_path.resolve())
    assert artifact["goldens_dir"] == str(GOLDENS_DIR.resolve())
    assert artifact["ok"] is True
    assert artifact["total"] == 680
    assert artifact["failed"] == 0
    assert artifact["artifact_context"]["freshness"]["status"] == "current_at_generation"

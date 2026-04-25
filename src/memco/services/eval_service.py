from __future__ import annotations

import json
import math
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from memco.api.deps import build_internal_actor
from memco.config import load_settings
from memco.db import get_connection
from memco.extractors.base import ExtractionContext
from memco.extractors.biography import extract as extract_biography
from memco.extractors.experiences import extract as extract_experiences
from memco.extractors.preferences import extract as extract_preferences
from memco.extractors.work import extract as extract_work
from memco.llm_usage import LLMUsageTracker
from memco.models.memory_fact import MemoryFactInput
from memco.models.retrieval import RetrievalRequest
from memco.repositories.candidate_repository import CandidateRepository
from memco.repositories.fact_repository import FactRepository
from memco.repositories.review_repository import ReviewRepository
from memco.repositories.source_repository import SourceRepository
from memco.runtime import ensure_runtime
from memco.services.candidate_service import CandidateService
from memco.services.consolidation_service import ConsolidationService
from memco.services.conversation_ingest_service import ConversationIngestService
from memco.services.extraction_service import ExtractionService
from memco.services.ingest_service import IngestService
from memco.services.publish_service import PublishService
from memco.services.refusal_service import RefusalService
from memco.services.retrieval_service import RetrievalService


@dataclass(frozen=True)
class EvalCase:
    name: str
    group: str
    query: str
    person_slug: str
    expect_refused: bool
    expected_values: tuple[str, ...] = ()
    forbidden_values: tuple[str, ...] = ()
    domain: str | None = None
    category: str | None = None
    temporal_mode: str = "auto"
    expected_support_level: str | None = None
    expected_hit_count: int | None = None
    expected_evidence_count_min: int | None = None
    expected_pending_review_count_min: int | None = None


@dataclass(frozen=True)
class EvalBehaviorCheck:
    name: str
    group: str
    description: str


class EvalService:
    CASES = (
        EvalCase(
            "supported_residence_current",
            "supported_fact",
            "Where does Alice Eval live?",
            "alice-eval",
            False,
            expected_values=("Lisbon",),
            domain="biography",
            category="residence",
            expected_support_level="supported",
            expected_hit_count=1,
            expected_evidence_count_min=1,
        ),
        EvalCase(
            "supported_preference_current",
            "supported_fact",
            "What does Alice Eval prefer?",
            "alice-eval",
            False,
            expected_values=("tea",),
            domain="preferences",
            category="preference",
            expected_support_level="supported",
            expected_hit_count=1,
            expected_evidence_count_min=2,
        ),
        EvalCase(
            "supported_work_employment",
            "supported_fact",
            "What does Alice Eval do for work?",
            "alice-eval",
            False,
            expected_values=("software engineer",),
            domain="work",
            category="employment",
            expected_support_level="supported",
            expected_hit_count=1,
            expected_evidence_count_min=1,
        ),
        EvalCase(
            "supported_experience_event",
            "supported_fact",
            "What did Alice Eval attend?",
            "alice-eval",
            False,
            expected_values=("PyCon",),
            domain="experiences",
            category="event",
            expected_support_level="supported",
            expected_hit_count=1,
            expected_evidence_count_min=1,
        ),
        EvalCase(
            "supported_experience_when",
            "supported_fact",
            "When did Alice Eval attend PyCon?",
            "alice-eval",
            False,
            expected_values=("2025",),
            domain="experiences",
            category="event",
            temporal_mode="when",
            expected_support_level="supported",
            expected_hit_count=1,
            expected_evidence_count_min=1,
        ),
        EvalCase(
            "supported_residence_when_valid_from",
            "temporal_update",
            "When did Alice Eval start living in Lisbon?",
            "alice-eval",
            False,
            expected_values=("since 2026-04-21t10:01:00z",),
            domain="biography",
            category="residence",
            temporal_mode="when",
            expected_support_level="supported",
            expected_hit_count=1,
            expected_evidence_count_min=1,
        ),
        EvalCase(
            "supported_experience_when_observed_only",
            "temporal_update",
            "When did Temporal Observed Eval attend WebSummit?",
            "temporal-observed-eval",
            False,
            expected_values=("exact event date is unknown", "recorded on 2026-04-21t10:11:00z"),
            domain="experiences",
            category="event",
            temporal_mode="when",
            expected_support_level="supported",
            expected_hit_count=1,
            expected_evidence_count_min=1,
        ),
        EvalCase(
            "ambiguous_experience_when_conflicting_dates",
            "temporal_update",
            "When did Temporal Conflict Eval attend React Summit?",
            "temporal-conflict-eval",
            True,
            expected_values=("conflicting memory evidence about the exact event date",),
            domain="experiences",
            category="event",
            temporal_mode="when",
            expected_support_level="ambiguous",
            expected_hit_count=2,
            expected_evidence_count_min=2,
        ),
        EvalCase(
            "supported_bob_preference_current",
            "supported_fact",
            "What does Bob Eval prefer?",
            "bob-eval",
            False,
            expected_values=("coffee",),
            domain="preferences",
            category="preference",
            expected_support_level="supported",
            expected_hit_count=1,
            expected_evidence_count_min=1,
        ),
        EvalCase(
            "supported_guest_user_residence",
            "supported_fact",
            "Where does Guest User Eval live?",
            "guest-user-eval",
            False,
            expected_values=("Lisbon",),
            domain="biography",
            category="residence",
            expected_support_level="supported",
            expected_hit_count=1,
            expected_evidence_count_min=1,
        ),
        EvalCase(
            "supported_residence_current_ru",
            "multilingual_support",
            "Где сейчас живет Alice Eval?",
            "alice-eval",
            False,
            expected_values=("Lisbon",),
            domain="biography",
            category="residence",
            temporal_mode="current",
            expected_support_level="supported",
            expected_hit_count=1,
            expected_evidence_count_min=1,
        ),
        EvalCase(
            "supported_preference_current_mixed_language",
            "multilingual_support",
            "Что Alice Eval likes сейчас?",
            "alice-eval",
            False,
            expected_values=("tea",),
            domain="preferences",
            category="preference",
            temporal_mode="current",
            expected_support_level="supported",
            expected_hit_count=1,
            expected_evidence_count_min=2,
        ),
        EvalCase(
            "partial_supported_employer_claim",
            "partial_support",
            "Does Alice Eval live in Lisbon and work at Stripe?",
            "alice-eval",
            True,
            expected_values=("Lisbon",),
            temporal_mode="auto",
            expected_support_level="partial",
            expected_hit_count=2,
            expected_evidence_count_min=2,
        ),
        EvalCase(
            "contradicted_residence_claim",
            "contradicted_premise",
            "Does Alice Eval live in Berlin?",
            "alice-eval",
            True,
            expected_values=("Lisbon",),
            forbidden_values=("Berlin",),
            domain="biography",
            category="residence",
            expected_support_level="contradicted",
            expected_hit_count=1,
            expected_evidence_count_min=1,
        ),
        EvalCase(
            "unsupported_false_premise_sister",
            "unsupported_premise",
            "Does Alice Eval have a sister?",
            "alice-eval",
            True,
            domain="social_circle",
            category="sister",
            expected_support_level="unsupported",
            expected_hit_count=0,
        ),
        EvalCase(
            "style_psychometric_non_leakage",
            "style_psychometric_non_leakage",
            "Does Style Eval own a cat?",
            "style-eval",
            True,
            expected_support_level="unsupported",
            expected_hit_count=0,
        ),
        EvalCase(
            "cross_person_alice_preference_isolation",
            "cross_person_contamination",
            "What does Alice Eval prefer?",
            "alice-eval",
            False,
            expected_values=("tea",),
            forbidden_values=("coffee",),
            domain="preferences",
            category="preference",
            expected_support_level="supported",
            expected_hit_count=1,
            expected_evidence_count_min=2,
        ),
        EvalCase(
            "cross_person_bob_preference_isolation",
            "cross_person_contamination",
            "What does Bob Eval prefer?",
            "bob-eval",
            False,
            expected_values=("coffee",),
            forbidden_values=("tea",),
            domain="preferences",
            category="preference",
            expected_support_level="supported",
            expected_hit_count=1,
            expected_evidence_count_min=1,
        ),
        EvalCase(
            "cross_person_alice_residence_isolation",
            "cross_person_contamination",
            "Where does Alice Eval live?",
            "alice-eval",
            False,
            expected_values=("Lisbon",),
            forbidden_values=("Porto",),
            domain="biography",
            category="residence",
            expected_support_level="supported",
            expected_hit_count=1,
            expected_evidence_count_min=1,
        ),
        EvalCase(
            "temporal_history_before_lisbon",
            "temporal_update",
            "Where did Alice Eval live before Lisbon?",
            "alice-eval",
            False,
            expected_values=("Berlin",),
            forbidden_values=("Lisbon",),
            domain="biography",
            category="residence",
            temporal_mode="history",
            expected_support_level="supported",
            expected_hit_count=1,
            expected_evidence_count_min=1,
        ),
        EvalCase(
            "temporal_history_used_to_live",
            "temporal_update",
            "Where did Alice Eval use to live?",
            "alice-eval",
            False,
            expected_values=("Berlin",),
            forbidden_values=("Lisbon",),
            domain="biography",
            category="residence",
            temporal_mode="history",
            expected_support_level="supported",
            expected_hit_count=1,
            expected_evidence_count_min=1,
        ),
        EvalCase(
            "temporal_current_now",
            "temporal_update",
            "Where does Alice Eval live now?",
            "alice-eval",
            False,
            expected_values=("Lisbon",),
            domain="biography",
            category="residence",
            temporal_mode="current",
            expected_support_level="supported",
            expected_hit_count=1,
            expected_evidence_count_min=1,
        ),
        EvalCase(
            "duplicate_merge_preference_evidence",
            "duplicate_merge",
            "What does Alice Eval like?",
            "alice-eval",
            False,
            expected_values=("tea",),
            domain="preferences",
            category="preference",
            expected_support_level="supported",
            expected_hit_count=1,
            expected_evidence_count_min=2,
        ),
        EvalCase(
            "duplicate_merge_preference_yes_no",
            "duplicate_merge",
            "Does Alice Eval like tea?",
            "alice-eval",
            False,
            expected_values=("tea",),
            domain="preferences",
            category="preference",
            expected_support_level="supported",
            expected_hit_count=1,
            expected_evidence_count_min=2,
        ),
        EvalCase(
            "review_queue_blocks_social_answer",
            "review_queue_behavior",
            "Who is Alice Eval friends with?",
            "alice-eval",
            True,
            domain="social_circle",
            expected_support_level="unsupported",
            expected_hit_count=0,
            expected_pending_review_count_min=1,
        ),
        EvalCase(
            "rollback_truth_preserves_current",
            "rollback_truth_preservation",
            "Where does Carol Eval live?",
            "carol-eval",
            False,
            expected_values=("Berlin",),
            forbidden_values=("Lisbon",),
            domain="biography",
            category="residence",
            expected_support_level="supported",
            expected_hit_count=1,
            expected_evidence_count_min=1,
        ),
        EvalCase(
            "rollback_truth_preserves_current_now",
            "rollback_truth_preservation",
            "Where does Carol Eval live now?",
            "carol-eval",
            False,
            expected_values=("Berlin",),
            forbidden_values=("Lisbon",),
            domain="biography",
            category="residence",
            temporal_mode="current",
            expected_support_level="supported",
            expected_hit_count=1,
            expected_evidence_count_min=1,
        ),
    )

    BENCHMARK_CASE_GROUPS = {
        "supported_fact",
        "partial_support",
        "unsupported_premise",
        "cross_person_contamination",
        "temporal_update",
        "duplicate_merge",
    }
    OPERATOR_READINESS_CASE_GROUPS = {
        "supported_fact",
        "temporal_update",
        "cross_person_contamination",
        "unsupported_premise",
        "contradicted_premise",
        "review_queue_behavior",
    }
    BENCHMARK_SETS = {
        "internal_golden_set": {"supported_fact", "duplicate_merge"},
        "adversarial_false_premise_set": {"unsupported_premise", "partial_support"},
        "temporal_set": {"temporal_update"},
        "cross_person_contamination_set": {"cross_person_contamination"},
        "operator_readiness_set": OPERATOR_READINESS_CASE_GROUPS,
    }
    PERSONAL_MEMORY_REQUIRED_COUNTS = {
        "core_fact": 100,
        "adversarial_false_premise": 50,
        "social_family": 50,
        "temporal": 50,
        "preference": 50,
        "cross_person_contamination": 30,
        "speakerless_note": 30,
        "rollback_update": 20,
    }
    PERSONAL_MEMORY_THRESHOLDS = {
        "overall_accuracy": 0.90,
        "core_memory_accuracy": 0.95,
        "adversarial_robustness": 0.98,
        "temporal_accuracy": 0.90,
        "cross_person_contamination": 0,
        "unsupported_premise_answered_as_fact": 0,
        "evidence_missing_on_supported_answers": 0,
        "speakerless_owner_fallback_accuracy": 0.95,
        "tool_project_retrieval_pass_rate": 0.95,
        "experience_event_retrieval_pass_rate": 0.90,
        "source_hard_case_failures": 0,
    }
    P1_8_PRIVATE_EVAL_TARGET_COUNTS = {
        "core_biography": 100,
        "preference_current_state": 100,
        "social_graph": 100,
        "work_project_tool": 100,
        "experiences_temporal": 150,
        "adversarial_false_premise": 150,
        "cross_person_contamination": 50,
        "update_supersession": 50,
        "multi_hop": 50,
    }
    P1_8_PRIVATE_EVAL_THRESHOLDS = {
        "overall_accuracy": 0.92,
        "core_biography_accuracy": 0.96,
        "preference_current_state_accuracy": 0.95,
        "work_project_tool_accuracy": 0.95,
        "social_graph_accuracy": 0.93,
        "experiences_single_hop_accuracy": 0.93,
        "temporal_accuracy": 0.90,
        "adversarial_refusal_accuracy": 0.98,
        "cross_person_contamination": 0,
        "unsupported_personal_claims_answered_as_fact": 0,
    }
    P2_3_LONG_CORPUS_TARGET_MESSAGE_COUNTS = (50_000, 500_000)
    P2_3_LONG_CORPUS_REQUIRED_DIMENSIONS = (
        "mixed_sources",
        "old_and_new_contradictions",
        "multiple_people",
        "repeated_updates",
        "extraction_cost",
        "candidate_volume",
        "fact_growth",
        "retrieval_latency",
        "false_positive_retrieval",
        "refusal_quality",
    )
    PERSONAL_MEMORY_COVERAGE_GROUPS = {
        "single_hop": {"core_fact", "preference", "speakerless_note"},
        "multi_hop": {"social_family"},
        "temporal": {"temporal", "rollback_update"},
        "open_inference": {"speakerless_note"},
        "adversarial_false_premise": {"adversarial_false_premise"},
        "cross_person": {"cross_person_contamination"},
    }
    LOCOMO_LIKE_MANIFEST_NAME = "locomo_like_suite_manifest.json"
    LOCOMO_LIKE_MIN_CONVERSATIONS = 10
    LOCOMO_LIKE_MIN_PERSONS_PER_CONVERSATION = 2
    LOCOMO_LIKE_DEFAULT_MIN_TURNS = 50

    BEHAVIOR_CHECKS = (
        EvalBehaviorCheck(
            "pending_review_item_created",
            "review_queue_behavior",
            "Unresolved speaker extraction should leave at least one pending review item.",
        ),
        EvalBehaviorCheck(
            "speaker_resolution_can_publish",
            "review_queue_behavior",
            "Manual speaker resolution should produce a publishable biography candidate for Guest User Eval.",
        ),
        EvalBehaviorCheck(
            "duplicate_merge_retains_two_evidence_items",
            "duplicate_merge",
            "Duplicate merge should keep one active fact with at least two evidence rows.",
        ),
        EvalBehaviorCheck(
            "rollback_truth_store_single_active",
            "rollback_truth_preservation",
            "Rollback should leave exactly one active current-state residence fact for Carol Eval.",
        ),
    )

    def __init__(
        self,
        retrieval_service: RetrievalService | None = None,
        refusal_service: RefusalService | None = None,
    ) -> None:
        self.llm_usage_tracker = LLMUsageTracker()
        self.retrieval_service = retrieval_service or RetrievalService(usage_tracker=self.llm_usage_tracker)
        self.refusal_service = refusal_service or RefusalService(usage_tracker=self.llm_usage_tracker)

    def _person(self, conn, *, fact_repo: FactRepository, slug: str, display_name: str) -> dict:
        return fact_repo.upsert_person(
            conn,
            workspace_slug="default",
            display_name=display_name,
            slug=slug,
            person_type="human",
            aliases=[display_name],
        )

    def _record_source(
        self,
        conn,
        *,
        source_repo: SourceRepository,
        source_path: str,
        title: str,
        sha256: str,
        parsed_text: str,
        source_type: str = "note",
    ) -> int:
        return source_repo.record_source(
            conn,
            workspace_slug="default",
            source_path=source_path,
            source_type=source_type,
            origin_uri=f"eval://{title}",
            title=title,
            sha256=sha256,
            parsed_text=parsed_text,
        )

    def _get_fact_by_canonical_key(self, conn, *, canonical_key: str) -> dict | None:
        row = conn.execute(
            "SELECT id FROM memory_facts WHERE canonical_key = ? ORDER BY id DESC LIMIT 1",
            (canonical_key,),
        ).fetchone()
        if row is None:
            return None
        return FactRepository().get_fact(conn, fact_id=int(row["id"]))

    def _ensure_fact(
        self,
        conn,
        *,
        consolidation: ConsolidationService,
        canonical_key: str,
        payload: dict,
        person_id: int,
        domain: str,
        category: str,
        summary: str,
        observed_at: str,
        valid_from: str = "",
        event_at: str = "",
        source_id: int,
        quote_text: str,
        subcategory: str = "",
    ) -> dict:
        existing = self._get_fact_by_canonical_key(conn, canonical_key=canonical_key)
        if existing is not None:
            return existing
        return consolidation.add_fact(
            conn,
            MemoryFactInput(
                workspace="default",
                person_id=person_id,
                domain=domain,
                category=category,
                subcategory=subcategory,
                canonical_key=canonical_key,
                payload=payload,
                summary=summary,
                confidence=0.95,
                observed_at=observed_at,
                valid_from=valid_from,
                event_at=event_at,
                source_id=source_id,
                quote_text=quote_text,
            ),
        )

    def _ensure_json_source(self, project_root: Path, filename: str, messages: list[dict]) -> Path:
        source_dir = project_root / "var" / "raw" / "eval"
        source_dir.mkdir(parents=True, exist_ok=True)
        path = source_dir / filename
        payload = {"messages": messages}
        path.write_text(__import__("json").dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return path

    def _ensure_imported_conversation(
        self,
        settings,
        conn,
        *,
        ingest_service: IngestService,
        conversation_service: ConversationIngestService,
        filename: str,
        messages: list[dict],
        conversation_uid: str,
        title: str,
    ) -> tuple[int, int]:
        path = self._ensure_json_source(settings.root, filename, messages)
        imported = ingest_service.import_file(
            settings,
            conn,
            workspace_slug="default",
            path=path,
            source_type="json",
        )
        conversation = conversation_service.import_conversation(
            settings,
            conn,
            workspace_slug="default",
            source_id=imported.source_id,
            conversation_uid=conversation_uid,
            title=title,
        )
        return imported.source_id, conversation.conversation_id

    def seed_fixture_data(self, project_root: Path) -> None:
        settings = load_settings(project_root)
        settings.runtime.profile = "fixture"
        settings.llm.provider = "mock"
        settings.llm.model = "fixture"
        settings.llm.allow_mock_provider = True
        self.llm_usage_tracker.reset()
        fact_repo = FactRepository()
        source_repo = SourceRepository()
        consolidation = ConsolidationService(fact_repository=fact_repo)
        ingest_service = IngestService(source_repository=source_repo)
        conversation_service = ConversationIngestService()
        candidate_service = CandidateService(
            extraction_service=ExtractionService.from_settings(settings, usage_tracker=self.llm_usage_tracker)
        )
        candidate_repo = CandidateRepository()
        publish_service = PublishService()
        review_repo = ReviewRepository()

        with get_connection(settings.db_path) as conn:
            alice = self._person(conn, fact_repo=fact_repo, slug="alice-eval", display_name="Alice Eval")
            bob = self._person(conn, fact_repo=fact_repo, slug="bob-eval", display_name="Bob Eval")
            carol = self._person(conn, fact_repo=fact_repo, slug="carol-eval", display_name="Carol Eval")
            self._person(conn, fact_repo=fact_repo, slug="guest-user-eval", display_name="Guest User Eval")
            self._person(conn, fact_repo=fact_repo, slug="style-eval", display_name="Style Eval")
            temporal_observed = self._person(
                conn,
                fact_repo=fact_repo,
                slug="temporal-observed-eval",
                display_name="Temporal Observed Eval",
            )
            temporal_conflict = self._person(
                conn,
                fact_repo=fact_repo,
                slug="temporal-conflict-eval",
                display_name="Temporal Conflict Eval",
            )

            direct_main = self._record_source(
                conn,
                source_repo=source_repo,
                source_path="var/raw/eval/direct-main.md",
                title="eval-direct-main",
                sha256="eval-direct-main-sha",
                parsed_text="Main eval fixture facts.",
            )
            direct_duplicate = self._record_source(
                conn,
                source_repo=source_repo,
                source_path="var/raw/eval/direct-duplicate.md",
                title="eval-direct-duplicate",
                sha256="eval-direct-duplicate-sha",
                parsed_text="Duplicate evidence fixture facts.",
            )
            direct_style = self._record_source(
                conn,
                source_repo=source_repo,
                source_path="var/raw/eval/direct-style.md",
                title="eval-direct-style",
                sha256="eval-direct-style-sha",
                parsed_text="Style and psychometric fixture facts.",
            )

            alice_berlin_key = "alice-eval:biography:residence:berlin"
            alice_lisbon_key = "alice-eval:biography:residence:lisbon"
            alice_berlin = self._get_fact_by_canonical_key(conn, canonical_key=alice_berlin_key)
            alice_lisbon = self._get_fact_by_canonical_key(conn, canonical_key=alice_lisbon_key)
            if not (
                alice_berlin is not None
                and alice_lisbon is not None
                and alice_berlin["status"] == "superseded"
                and alice_lisbon["status"] == "active"
            ):
                if alice_berlin is None:
                    self._ensure_fact(
                        conn,
                        consolidation=consolidation,
                        canonical_key=alice_berlin_key,
                        payload={"city": "Berlin"},
                        person_id=int(alice["id"]),
                        domain="biography",
                        category="residence",
                        summary="Alice Eval lives in Berlin.",
                        observed_at="2025-04-21T10:00:00Z",
                        source_id=direct_main,
                        quote_text="Alice Eval lived in Berlin.",
                    )
                alice_lisbon = self._get_fact_by_canonical_key(conn, canonical_key=alice_lisbon_key)
                if alice_lisbon is None or alice_lisbon["status"] != "active":
                    consolidation.add_fact(
                        conn,
                        MemoryFactInput(
                            workspace="default",
                            person_id=int(alice["id"]),
                            domain="biography",
                            category="residence",
                            canonical_key=alice_lisbon_key,
                            payload={"city": "Lisbon"},
                            summary="Alice Eval lives in Lisbon.",
                            confidence=0.95,
                            observed_at="2026-04-21T10:01:00Z",
                            source_id=direct_main,
                            quote_text="Alice Eval moved to Lisbon.",
                        ),
                    )

            alice_tea_key = "alice-eval:preferences:preference:tea"
            tea_fact = self._ensure_fact(
                conn,
                consolidation=consolidation,
                canonical_key=alice_tea_key,
                payload={"value": "tea"},
                person_id=int(alice["id"]),
                domain="preferences",
                category="preference",
                summary="Alice Eval likes tea.",
                observed_at="2026-04-21T10:02:00Z",
                source_id=direct_main,
                quote_text="Alice Eval likes tea.",
            )
            if len(tea_fact["evidence"]) < 2:
                consolidation.add_fact(
                    conn,
                    MemoryFactInput(
                        workspace="default",
                        person_id=int(alice["id"]),
                        domain="preferences",
                        category="preference",
                        canonical_key=alice_tea_key,
                        payload={"value": "tea"},
                        summary="Alice Eval likes tea.",
                        confidence=0.94,
                        observed_at="2026-04-21T10:03:00Z",
                        source_id=direct_duplicate,
                        quote_text="Alice Eval likes tea a lot.",
                    ),
                )

            self._ensure_fact(
                conn,
                consolidation=consolidation,
                canonical_key="alice-eval:work:employment:software-engineer",
                payload={"title": "software engineer"},
                person_id=int(alice["id"]),
                domain="work",
                category="employment",
                summary="Alice Eval works as software engineer.",
                observed_at="2026-04-21T10:04:00Z",
                source_id=direct_main,
                quote_text="Alice Eval works as software engineer.",
            )
            self._ensure_fact(
                conn,
                consolidation=consolidation,
                canonical_key="alice-eval:experiences:event:pycon",
                payload={"event": "PyCon", "event_at": "2025"},
                person_id=int(alice["id"]),
                domain="experiences",
                category="event",
                summary="Alice Eval attended PyCon.",
                observed_at="2026-04-21T10:05:00Z",
                source_id=direct_main,
                event_at="2025",
                quote_text="Alice Eval attended PyCon in 2025.",
            )
            self._ensure_fact(
                conn,
                consolidation=consolidation,
                canonical_key="bob-eval:preferences:preference:coffee",
                payload={"value": "coffee"},
                person_id=int(bob["id"]),
                domain="preferences",
                category="preference",
                summary="Bob Eval prefers coffee.",
                observed_at="2026-04-21T10:06:00Z",
                source_id=direct_main,
                quote_text="Bob Eval prefers coffee.",
            )
            self._ensure_fact(
                conn,
                consolidation=consolidation,
                canonical_key="bob-eval:biography:residence:porto",
                payload={"city": "Porto"},
                person_id=int(bob["id"]),
                domain="biography",
                category="residence",
                summary="Bob Eval lives in Porto.",
                observed_at="2026-04-21T10:07:00Z",
                source_id=direct_main,
                quote_text="Bob Eval lives in Porto.",
            )
            self._ensure_fact(
                conn,
                consolidation=consolidation,
                canonical_key="bob-eval:experiences:event:websummit",
                payload={"event": "WebSummit"},
                person_id=int(bob["id"]),
                domain="experiences",
                category="event",
                summary="Bob Eval attended WebSummit.",
                observed_at="2026-04-21T10:11:00Z",
                source_id=direct_main,
                quote_text="Bob Eval attended WebSummit.",
            )
            self._ensure_fact(
                conn,
                consolidation=consolidation,
                canonical_key="bob-eval:experiences:event:react-summit-2024",
                payload={"event": "React Summit", "event_at": "2024"},
                person_id=int(bob["id"]),
                domain="experiences",
                category="event",
                summary="Bob Eval attended React Summit.",
                observed_at="2026-04-21T10:12:00Z",
                event_at="2024",
                source_id=direct_main,
                quote_text="Bob Eval attended React Summit in 2024.",
            )
            self._ensure_fact(
                conn,
                consolidation=consolidation,
                canonical_key="bob-eval:experiences:event:react-summit-2025",
                payload={"event": "React Summit", "event_at": "2025"},
                person_id=int(bob["id"]),
                domain="experiences",
                category="event",
                summary="Bob Eval attended React Summit.",
                observed_at="2026-04-21T10:13:00Z",
                event_at="2025",
                source_id=direct_main,
                quote_text="Bob Eval attended React Summit in 2025.",
            )
            self._ensure_fact(
                conn,
                consolidation=consolidation,
                canonical_key="temporal-observed-eval:experiences:event:websummit",
                payload={"event": "WebSummit"},
                person_id=int(temporal_observed["id"]),
                domain="experiences",
                category="event",
                summary="Temporal Observed Eval attended WebSummit.",
                observed_at="2026-04-21T10:11:00Z",
                source_id=direct_main,
                quote_text="Temporal Observed Eval attended WebSummit.",
            )
            self._ensure_fact(
                conn,
                consolidation=consolidation,
                canonical_key="temporal-conflict-eval:experiences:event:react-summit-2024",
                payload={"event": "React Summit", "event_at": "2024"},
                person_id=int(temporal_conflict["id"]),
                domain="experiences",
                category="event",
                summary="Temporal Conflict Eval attended React Summit.",
                observed_at="2026-04-21T10:12:00Z",
                event_at="2024",
                source_id=direct_main,
                quote_text="Temporal Conflict Eval attended React Summit in 2024.",
            )
            self._ensure_fact(
                conn,
                consolidation=consolidation,
                canonical_key="temporal-conflict-eval:experiences:event:react-summit-2025",
                payload={"event": "React Summit", "event_at": "2025"},
                person_id=int(temporal_conflict["id"]),
                domain="experiences",
                category="event",
                summary="Temporal Conflict Eval attended React Summit.",
                observed_at="2026-04-21T10:13:00Z",
                event_at="2025",
                source_id=direct_main,
                quote_text="Temporal Conflict Eval attended React Summit in 2025.",
            )
            self._ensure_fact(
                conn,
                consolidation=consolidation,
                canonical_key="style-eval:style:communication_style:humorous",
                payload={"tone": "humorous", "generation_guidance": "Use light humor."},
                person_id=int(fact_repo.resolve_person_id(conn, workspace_slug="default", person_slug="style-eval")),
                domain="style",
                category="communication_style",
                summary="Style Eval often communicates humorously.",
                observed_at="2026-04-21T10:08:00Z",
                source_id=direct_style,
                quote_text="Haha.",
            )
            self._ensure_fact(
                conn,
                consolidation=consolidation,
                canonical_key="style-eval:psychometrics:big_five:openness",
                payload={
                    "framework": "big_five",
                    "trait": "openness",
                    "extracted_signal": {
                        "signal_kind": "explicit_self_description",
                        "explicit_self_description": True,
                        "signal_confidence": 0.72,
                        "evidence_count": 1,
                        "counterevidence_count": 1,
                        "evidence_quotes": [
                            {"quote": "I am very curious.", "message_ids": ["2"], "interpretation": "Possible signal for openness."}
                        ],
                        "counterevidence_quotes": [
                            {
                                "quote": "I am very curious.",
                                "message_ids": ["2"],
                                "interpretation": "No direct counterevidence found in this snippet; update conservatively for openness.",
                            }
                        ],
                        "observed_at": "2026-04-21T10:09:00Z",
                    },
                    "scored_profile": {
                        "score": 0.7,
                        "score_scale": "0_1",
                        "direction": "high",
                        "confidence": 0.55,
                        "framework_threshold": 0.7,
                        "conservative_update": True,
                        "use_in_generation": False,
                    },
                    "score": 0.7,
                    "score_scale": "0_1",
                    "direction": "high",
                    "confidence": 0.55,
                    "evidence_quotes": [
                        {"quote": "I am very curious.", "message_ids": ["2"], "interpretation": "Possible signal for openness."}
                    ],
                    "counterevidence_quotes": [
                        {
                            "quote": "I am very curious.",
                            "message_ids": ["2"],
                            "interpretation": "No direct counterevidence found in this snippet; update conservatively for openness.",
                        }
                    ],
                    "conservative_update": True,
                    "last_updated": "2026-04-21T10:09:00Z",
                    "use_in_generation": False,
                    "safety_notes": "Non-diagnostic psychometric hint; do not use as factual evidence.",
                },
                person_id=int(fact_repo.resolve_person_id(conn, workspace_slug="default", person_slug="style-eval")),
                domain="psychometrics",
                category="trait",
                subcategory="big_five",
                summary="Style Eval may score high on openness.",
                observed_at="2026-04-21T10:09:00Z",
                source_id=direct_style,
                quote_text="I am very curious.",
            )

            carol_berlin_key = "carol-eval:biography:residence:berlin"
            carol_lisbon_key = "carol-eval:biography:residence:lisbon"
            carol_berlin = self._get_fact_by_canonical_key(conn, canonical_key=carol_berlin_key)
            carol_lisbon = self._get_fact_by_canonical_key(conn, canonical_key=carol_lisbon_key)
            if not (
                carol_berlin is not None
                and carol_lisbon is not None
                and carol_berlin["status"] == "active"
                and carol_lisbon["status"] == "deleted"
            ):
                if carol_berlin is None:
                    self._ensure_fact(
                        conn,
                        consolidation=consolidation,
                        canonical_key=carol_berlin_key,
                        payload={"city": "Berlin"},
                        person_id=int(carol["id"]),
                        domain="biography",
                        category="residence",
                        summary="Carol Eval lives in Berlin.",
                        observed_at="2025-04-21T10:00:00Z",
                        source_id=direct_main,
                        quote_text="Carol Eval lived in Berlin.",
                    )
                carol_lisbon = self._get_fact_by_canonical_key(conn, canonical_key=carol_lisbon_key)
                if carol_lisbon is None or carol_lisbon["status"] != "deleted":
                    if carol_lisbon is None or carol_lisbon["status"] != "active":
                        consolidation.add_fact(
                            conn,
                            MemoryFactInput(
                                workspace="default",
                                person_id=int(carol["id"]),
                                domain="biography",
                                category="residence",
                                canonical_key=carol_lisbon_key,
                                payload={"city": "Lisbon"},
                                summary="Carol Eval lives in Lisbon.",
                                confidence=0.95,
                                observed_at="2026-04-21T10:10:00Z",
                                source_id=direct_main,
                                quote_text="Carol Eval moved to Lisbon.",
                            ),
                        )
                    carol_berlin = self._get_fact_by_canonical_key(conn, canonical_key=carol_berlin_key)
                    supersede_operation = conn.execute(
                        """
                        SELECT id
                        FROM memory_operations
                        WHERE target_fact_id = ? AND operation_type = 'superseded'
                        ORDER BY id DESC
                        LIMIT 1
                        """,
                        (int(carol_berlin["id"]),),
                    ).fetchone()
                    if supersede_operation is not None:
                        consolidation.rollback(
                            conn,
                            operation_id=int(supersede_operation["id"]),
                            reason="eval fixture rollback",
                        )

            guest_source_id, guest_conversation_id = self._ensure_imported_conversation(
                settings,
                conn,
                ingest_service=ingest_service,
                conversation_service=conversation_service,
                filename="guest-user-move.json",
                messages=[
                    {"speaker": "Guest", "timestamp": "2026-04-21T10:00:00Z", "text": "I moved to Lisbon."},
                ],
                conversation_uid="guest-user-move",
                title="Guest User Eval Move",
            )
            guest_lisbon = self._get_fact_by_canonical_key(conn, canonical_key="guest-user-eval:biography:residence:lisbon")
            if guest_lisbon is None or guest_lisbon["status"] != "active":
                conversation_service.resolve_speaker(
                    conn,
                    workspace_slug="default",
                    conversation_id=guest_conversation_id,
                    speaker_key="guest",
                    person_slug="guest-user-eval",
                )
                guest_candidates = candidate_service.reextract_for_speaker_resolution(
                    conn,
                    workspace_slug="default",
                    conversation_id=guest_conversation_id,
                )
                guest_biography = next(item for item in guest_candidates if item["domain"] == "biography")
                publish_service.publish_candidate(
                    conn,
                    workspace_slug="default",
                    candidate_id=int(guest_biography["id"]),
                )

            _pending_source_id, pending_conversation_id = self._ensure_imported_conversation(
                settings,
                conn,
                ingest_service=ingest_service,
                conversation_service=conversation_service,
                filename="ally-review-social.json",
                messages=[
                    {"speaker": "Ally", "timestamp": "2026-04-21T10:00:00Z", "text": "Bob Eval is my friend."},
                ],
                conversation_uid="ally-review-social",
                title="Ally Review Social",
            )
            pending_candidate_row = conn.execute(
                """
                SELECT id
                FROM fact_candidates
                WHERE conversation_id = ? AND domain = 'social_circle'
                ORDER BY id DESC
                LIMIT 1
                """,
                (pending_conversation_id,),
            ).fetchone()
            if pending_candidate_row is None:
                candidate_service.extract_from_conversation(
                    conn,
                    workspace_slug="default",
                    conversation_id=pending_conversation_id,
                )
                pending_candidate_row = conn.execute(
                    """
                    SELECT id
                    FROM fact_candidates
                    WHERE conversation_id = ? AND domain = 'social_circle'
                    ORDER BY id DESC
                    LIMIT 1
                    """,
                    (pending_conversation_id,),
                ).fetchone()
            if pending_candidate_row is not None:
                pending_candidate = candidate_repo.get_candidate(conn, candidate_id=int(pending_candidate_row["id"]))
                pending_reviews = review_repo.list_items(conn, workspace_slug="default", status="pending")
                if not any(int(item.get("candidate_id") or 0) == int(pending_candidate["id"]) for item in pending_reviews):
                    review_repo.enqueue(
                        conn,
                        workspace_slug="default",
                        person_id=pending_candidate.get("person_id"),
                        candidate=pending_candidate,
                        reason=pending_candidate.get("reason") or "needs_review",
                        candidate_id=int(pending_candidate["id"]),
                    )

    def _behavior_checks(self, conn) -> list[dict]:
        fact_repo = FactRepository()
        review_repo = ReviewRepository()
        guest_person_id = fact_repo.resolve_person_id(conn, workspace_slug="default", person_slug="guest-user-eval")
        guest_fact_row = conn.execute(
            """
            SELECT id
            FROM memory_facts
            WHERE person_id = ? AND domain = 'biography' AND category = 'residence' AND status = 'active'
            ORDER BY id DESC
            LIMIT 1
            """,
            (guest_person_id,),
        ).fetchone()
        guest_fact = None
        if guest_fact_row is not None:
            guest_fact = fact_repo.get_fact(conn, fact_id=int(guest_fact_row["id"]))
        tea_fact = self._get_fact_by_canonical_key(conn, canonical_key="alice-eval:preferences:preference:tea")
        carol_berlin = self._get_fact_by_canonical_key(conn, canonical_key="carol-eval:biography:residence:berlin")
        carol_active = conn.execute(
            """
            SELECT id
            FROM memory_facts
            WHERE person_id = ? AND domain = 'biography' AND category = 'residence' AND status = 'active'
            ORDER BY id ASC
            """,
            (fact_repo.resolve_person_id(conn, workspace_slug="default", person_slug="carol-eval"),),
        ).fetchall()
        pending_reviews = review_repo.list_items(conn, workspace_slug="default", status="pending")
        return [
            {
                "name": "pending_review_item_created",
                "group": "review_queue_behavior",
                "description": "Unresolved speaker extraction should leave at least one pending review item.",
                "passed": len(pending_reviews) >= 1,
                "details": {"pending_review_count": len(pending_reviews)},
            },
            {
                "name": "speaker_resolution_can_publish",
                "group": "review_queue_behavior",
                "description": "Manual speaker resolution should produce a publishable biography candidate for Guest User Eval.",
                "passed": guest_fact is not None and guest_fact["status"] == "active",
                "details": {
                    "guest_user_fact_status": guest_fact["status"] if guest_fact is not None else None,
                    "guest_user_city": guest_fact["payload"].get("city") if guest_fact is not None else None,
                },
            },
            {
                "name": "duplicate_merge_retains_two_evidence_items",
                "group": "duplicate_merge",
                "description": "Duplicate merge should keep one active fact with at least two evidence rows.",
                "passed": tea_fact is not None and len(tea_fact["evidence"]) >= 2,
                "details": {"evidence_count": len(tea_fact["evidence"]) if tea_fact is not None else 0},
            },
            {
                "name": "rollback_truth_store_single_active",
                "group": "rollback_truth_preservation",
                "description": "Rollback should leave exactly one active current-state residence fact for Carol Eval.",
                "passed": len(carol_active) == 1
                and carol_berlin is not None
                and carol_berlin["status"] == "active",
                "details": {"active_fact_ids": [int(row["id"]) for row in carol_active]},
            },
        ]

    def _combined_case_text(self, *, answer: dict, retrieval, include_answer: bool = True) -> str:
        payload_text = " ".join(
            str(value)
            for hit in retrieval.hits
            for value in hit.payload.values()
        )
        summary_text = " ".join(hit.summary for hit in retrieval.hits)
        evidence_text = " ".join(
            evidence.get("quote_text", "")
            for hit in retrieval.hits
            for evidence in hit.evidence
        )
        answer_text = answer["answer"] if include_answer else ""
        return " ".join([answer_text, summary_text, payload_text, evidence_text]).lower()

    def _latency_summary(self, values: list[int]) -> dict:
        if not values:
            return {"min": 0, "max": 0, "avg": 0.0, "p50": 0, "p95": 0}
        ordered = sorted(values)
        p50_index = max(0, math.ceil(len(ordered) * 0.50) - 1)
        p95_index = max(0, math.ceil(len(ordered) * 0.95) - 1)
        return {
            "min": ordered[0],
            "max": ordered[-1],
            "avg": round(sum(ordered) / len(ordered), 2),
            "p50": ordered[p50_index],
            "p95": ordered[p95_index],
        }

    def _execute_cases(self, project_root: Path, *, cases: tuple[EvalCase, ...], route_name: str) -> tuple[list[dict], list[dict]]:
        settings = load_settings(project_root)
        review_repo = ReviewRepository()
        with get_connection(settings.db_path) as conn:
            eval_actor = build_internal_actor(settings, actor_id="eval-runner")
            pending_reviews = review_repo.list_items(conn, workspace_slug="default", status="pending")
            pending_review_count = len(pending_reviews)
            results = []
            for case in cases:
                started = time.perf_counter()
                retrieval = self.retrieval_service.retrieve(
                    conn,
                    RetrievalRequest(
                        workspace="default",
                        person_slug=case.person_slug,
                        query=case.query,
                        domain=case.domain,
                        category=case.category,
                        include_fallback=True,
                        temporal_mode=case.temporal_mode,
                        actor=eval_actor,
                    ),
                    settings=settings,
                    route_name=route_name,
                )
                latency_ms = max(0, int((time.perf_counter() - started) * 1000))
                answer = self.refusal_service.build_answer(query=case.query, retrieval_result=retrieval)
                combined_text = self._combined_case_text(answer=answer, retrieval=retrieval)
                evidence_count = sum(len(hit.evidence) for hit in retrieval.hits)
                answer_evidence_ids = list(answer.get("evidence_ids", []))
                failures: list[str] = []
                if answer["refused"] != case.expect_refused:
                    failures.append("refusal_mismatch")
                if case.expected_support_level is not None and retrieval.support_level != case.expected_support_level:
                    failures.append("support_level_mismatch")
                if case.expected_hit_count is not None and len(retrieval.hits) != case.expected_hit_count:
                    failures.append("hit_count_mismatch")
                if case.expected_evidence_count_min is not None and evidence_count < case.expected_evidence_count_min:
                    failures.append("evidence_count_too_low")
                if (
                    case.group in self.OPERATOR_READINESS_CASE_GROUPS
                    and not case.expect_refused
                    and case.expected_support_level in {"supported", "partial"}
                    and not answer_evidence_ids
                ):
                    failures.append("answer_evidence_ids_missing")
                if (
                    case.expected_pending_review_count_min is not None
                    and pending_review_count < case.expected_pending_review_count_min
                ):
                    failures.append("pending_review_count_too_low")
                if (
                    case.expected_pending_review_count_min is not None
                    and pending_review_count >= case.expected_pending_review_count_min
                    and (len(retrieval.hits) > 0 or retrieval.support_level != "unsupported" or not answer["refused"])
                ):
                    failures.append("pending_review_leakage")
                for value in case.expected_values:
                    if value.lower() not in combined_text:
                        failures.append(f"missing_expected_value:{value}")
                forbidden_text = self._combined_case_text(
                    answer=answer,
                    retrieval=retrieval,
                    include_answer=not answer.get("refused", False),
                )
                for value in case.forbidden_values:
                    if value.lower() in forbidden_text:
                        failures.append(f"forbidden_value_present:{value}")
                results.append(
                    {
                        "name": case.name,
                        "group": case.group,
                        "domain": case.domain or "mixed",
                        "category": case.category or "",
                        "query": case.query,
                        "passed": not failures,
                        "failures": failures,
                        "refused": answer["refused"],
                        "expected_refused": case.expect_refused,
                        "refusal_correct": answer["refused"] == case.expect_refused,
                        "support_level": retrieval.support_level,
                        "hit_count": len(retrieval.hits),
                        "fallback_hit_count": len(retrieval.fallback_hits),
                        "evidence_count": evidence_count,
                        "latency_ms": latency_ms,
                        "pending_review_count": pending_review_count,
                        "answer": answer["answer"],
                        "answer_fact_ids": list(answer.get("fact_ids", [])),
                        "answer_evidence_ids": answer_evidence_ids,
                        }
                )

            results.sort(key=lambda item: (item["group"], item["name"]))
            behavior_checks = self._behavior_checks(conn)
        return results, behavior_checks

    def _build_common_metrics(self, *, results: list[dict], start_event_index: int = 0) -> dict:
        total = len(results)
        passed = sum(1 for item in results if item["passed"])
        latencies = [int(item["latency_ms"]) for item in results]
        hit_cases = [item for item in results if item["hit_count"] > 0]
        evidence_cases = [item for item in hit_cases if item["evidence_count"] > 0]
        refusal_cases = [item for item in results if item["expected_refused"]]
        refusal_passed = sum(1 for item in refusal_cases if item["refusal_correct"])
        group_names = sorted({item["group"] for item in results})
        groups = []
        for name in group_names:
            group_cases = [item for item in results if item["group"] == name]
            group_passed = sum(1 for item in group_cases if item["passed"])
            groups.append(
                {
                    "name": name,
                    "total": len(group_cases),
                    "passed": group_passed,
                    "pass_rate": round(group_passed / len(group_cases), 4) if group_cases else 0.0,
                }
            )
        return {
            "total": total,
            "passed": passed,
            "failed": total - passed,
            "pass_rate": round(passed / total, 4) if total else 0.0,
            "accuracy": round(passed / total, 4) if total else 0.0,
            "refusal_correctness": {
                "total_cases": len(refusal_cases),
                "passed_cases": refusal_passed,
                "rate": round(refusal_passed / len(refusal_cases), 4) if refusal_cases else 0.0,
            },
            "evidence_coverage": {
                "cases_with_hits": len(hit_cases),
                "cases_with_evidence": len(evidence_cases),
                "rate": round(len(evidence_cases) / len(hit_cases), 4) if hit_cases else 0.0,
                "missing_evidence_cases": [item["name"] for item in hit_cases if item["evidence_count"] == 0],
            },
            "retrieval_latency_ms": self._latency_summary(latencies),
            "token_accounting": self.llm_usage_tracker.summary(start_index=start_event_index),
            "groups": groups,
        }

    def _benchmark_set_reports(self, *, results: list[dict]) -> dict[str, dict]:
        reports: dict[str, dict] = {}
        for set_name, groups in self.BENCHMARK_SETS.items():
            selected = [item for item in results if item["group"] in groups]
            passed = sum(1 for item in selected if item["passed"])
            reports[set_name] = {
                "groups": sorted(groups),
                "total": len(selected),
                "passed": passed,
                "pass_rate": round(passed / len(selected), 4) if selected else 0.0,
            }
        return reports

    def _usage_delta(self, before: dict, after: dict) -> dict:
        before_cost = before.get("estimated_cost_usd")
        after_cost = after.get("estimated_cost_usd")
        estimated_cost_usd = (
            round(max(0.0, after_cost - before_cost), 6)
            if before_cost is not None and after_cost is not None
            else None
        )
        return {
            "operation_count": max(0, after["operation_count"] - before["operation_count"]),
            "input_tokens": max(0, after["input_tokens"] - before["input_tokens"]),
            "output_tokens": max(0, after["output_tokens"] - before["output_tokens"]),
            "estimated_cost_usd": estimated_cost_usd,
            "cost_status": after.get("cost_status", "not_applicable"),
            "known_cost_event_count": max(0, int(after.get("known_cost_event_count", 0)) - int(before.get("known_cost_event_count", 0))),
            "unknown_cost_event_count": max(0, int(after.get("unknown_cost_event_count", 0)) - int(before.get("unknown_cost_event_count", 0))),
            "providers": sorted(set(before.get("providers", [])) | set(after.get("providers", []))),
        }

    def _token_accounting_by_stage(self, *, start_event_index: int) -> dict[str, dict]:
        stage_events = self.llm_usage_tracker.events[start_event_index:]

        def aggregate(stage: str) -> dict[str, object]:
            selected = [event for event in stage_events if event.metadata.get("stage") == stage]
            deterministic = [event for event in selected if event.deterministic]
            llm = [event for event in selected if not event.deterministic]
            if llm:
                status = "measured_llm"
            elif deterministic:
                status = "deterministic"
            else:
                status = "not_applicable"
            return {
                "status": status,
                "operation_count": len(selected),
                "input_tokens": sum(event.input_tokens for event in selected),
                "output_tokens": sum(event.output_tokens for event in selected),
                "providers": sorted({event.provider for event in selected}),
            }

        return {
            "extraction": aggregate("extraction"),
            "planner": aggregate("planner"),
            "retrieval": aggregate("retrieval"),
            "answer": aggregate("answer"),
        }

    def _benchmark_domain_reports(self, *, results: list[dict]) -> dict[str, dict]:
        reports: dict[str, dict] = {}
        domain_names = sorted({item["domain"] for item in results})
        for domain_name in domain_names:
            domain_cases = [item for item in results if item["domain"] == domain_name]
            passed = sum(1 for item in domain_cases if item["passed"])
            category_names = sorted({item["category"] for item in domain_cases if item["category"]})
            category_reports = {}
            for category_name in category_names:
                category_cases = [item for item in domain_cases if item["category"] == category_name]
                category_passed = sum(1 for item in category_cases if item["passed"])
                category_reports[category_name] = {
                    "total": len(category_cases),
                    "passed": category_passed,
                    "pass_rate": round(category_passed / len(category_cases), 4) if category_cases else 0.0,
                }
            reports[domain_name] = {
                "total": len(domain_cases),
                "passed": passed,
                "pass_rate": round(passed / len(domain_cases), 4) if domain_cases else 0.0,
                "categories": category_reports,
            }
        return reports

    def _run_acceptance_cases(self, project_root: Path) -> dict:
        start_event_index = len(self.llm_usage_tracker.events)
        results, behavior_checks = self._execute_cases(project_root, cases=self.CASES, route_name="eval")
        metrics = self._build_common_metrics(results=results, start_event_index=start_event_index)
        return {
            "artifact_type": "eval_acceptance_artifact",
            "release_scope": "private-single-user",
            **metrics,
            "behavior_checks": behavior_checks,
            "behavior_checks_total": len(behavior_checks),
            "behavior_checks_passed": sum(1 for item in behavior_checks if item["passed"]),
            "cases": results,
        }

    def run_acceptance(self, project_root: Path) -> dict:
        return self._run_acceptance_cases(project_root)

    def run_benchmark(self, project_root: Path) -> dict:
        benchmark_cases = tuple(case for case in self.CASES if case.group in self.BENCHMARK_CASE_GROUPS)
        operator_readiness_cases = tuple(case for case in self.CASES if case.group in self.OPERATOR_READINESS_CASE_GROUPS)
        start_event_index = len(self.llm_usage_tracker.events)
        results, _behavior_checks = self._execute_cases(project_root, cases=benchmark_cases, route_name="benchmark")
        operator_results, _operator_behavior_checks = self._execute_cases(
            project_root,
            cases=operator_readiness_cases,
            route_name="operator_readiness",
        )
        metrics = self._build_common_metrics(results=results, start_event_index=start_event_index)
        benchmark_sets = self._benchmark_set_reports(results=results)
        operator_readiness_passed = sum(1 for item in operator_results if item["passed"])
        operator_readiness_failures = [
            {
                "name": item["name"],
                "group": item["group"],
                "failures": item["failures"],
            }
            for item in operator_results
            if not item["passed"]
        ]
        token_accounting_by_stage = self._token_accounting_by_stage(start_event_index=start_event_index)
        unsupported_premise_supported_count = sum(
            1
            for item in results
            if item["group"] == "unsupported_premise" and item["support_level"] == "supported"
        )
        positive_answers_missing_evidence_ids = sum(
            1
            for item in results
            if not item["refused"] and len(item.get("answer_evidence_ids", [])) == 0
        )
        return {
            "artifact_type": "eval_benchmark_artifact",
            "release_scope": "benchmark-only",
            "benchmark_scope": "internal-approximation",
            "benchmark_disclaimer": "synthetic benchmark; not paper-equivalent",
            "operator_readiness_scope": "hand-authored-small-set",
            "benchmark_metrics": {
                "core_memory_accuracy": benchmark_sets["internal_golden_set"]["pass_rate"],
                "adversarial_robustness": benchmark_sets["adversarial_false_premise_set"]["pass_rate"],
                "person_isolation": benchmark_sets["cross_person_contamination_set"]["pass_rate"],
                "refusal_correctness": metrics["refusal_correctness"],
                "evidence_coverage": metrics["evidence_coverage"],
                "temporal_precision": benchmark_sets["temporal_set"]["pass_rate"],
                "unsupported_premise_supported_count": unsupported_premise_supported_count,
                "positive_answers_missing_evidence_ids": positive_answers_missing_evidence_ids,
                "retrieval_latency_ms": metrics["retrieval_latency_ms"],
                "token_accounting_by_stage": token_accounting_by_stage,
                "extra_prompt_tokens": token_accounting_by_stage["extraction"]["input_tokens"],
            },
            "operator_readiness_metrics": {
                "pass_rate": round(operator_readiness_passed / len(operator_results), 4)
                if operator_results
                else 0.0,
                "total": len(operator_results),
                "passed": operator_readiness_passed,
                "groups": sorted(self.OPERATOR_READINESS_CASE_GROUPS),
                "case_names": [item["name"] for item in operator_results],
                "failures": operator_readiness_failures,
            },
            "benchmark_thresholds": {
                "core_memory_accuracy_min": 0.9,
                "adversarial_robustness_min": 0.95,
                "person_isolation_min": 0.99,
                "unsupported_premise_supported_count_max": 0,
                "positive_answers_missing_evidence_ids_max": 0,
            },
            "benchmark_cases": results,
            "benchmark_sets": benchmark_sets,
            "operator_readiness_cases": operator_results,
            "domain_reports": self._benchmark_domain_reports(results=results),
        }

    def _load_personal_goldens(self, goldens_dir: Path) -> list[dict[str, Any]]:
        if not goldens_dir.exists() or not goldens_dir.is_dir():
            raise ValueError(f"Personal memory goldens directory does not exist: {goldens_dir}")
        cases: list[dict[str, Any]] = []
        for path in sorted(goldens_dir.glob("*.jsonl")):
            with path.open("r", encoding="utf-8") as handle:
                for line_number, raw_line in enumerate(handle, start=1):
                    line = raw_line.strip()
                    if not line:
                        continue
                    item = json.loads(line)
                    item["_source_file"] = str(path)
                    item["_line_number"] = line_number
                    cases.append(item)
        if not cases:
            raise ValueError(f"No personal memory JSONL cases found in {goldens_dir}")
        required = {"id", "group", "person_slug", "person_display_name", "query", "expect_refused", "expected_values", "seed_facts"}
        for item in cases:
            missing = sorted(required - set(item))
            if missing:
                raise ValueError(f"Personal golden {item.get('id', '<unknown>')} missing fields: {missing}")
        return cases

    def _seed_personal_goldens(self, project_root: Path, cases: list[dict[str, Any]]) -> None:
        settings = ensure_runtime(load_settings(project_root))
        fact_repo = FactRepository()
        source_repo = SourceRepository()
        consolidation = ConsolidationService(fact_repository=fact_repo)
        with get_connection(settings.db_path) as conn:
            people: dict[str, dict] = {}
            for case in cases:
                person_slug = str(case["person_slug"])
                if person_slug not in people:
                    people[person_slug] = self._person(
                        conn,
                        fact_repo=fact_repo,
                        slug=person_slug,
                        display_name=str(case["person_display_name"]),
                    )
                for fact in case.get("seed_facts", []):
                    fact_person_slug = str(fact.get("person_slug") or person_slug)
                    if fact_person_slug not in people:
                        people[fact_person_slug] = self._person(
                            conn,
                            fact_repo=fact_repo,
                            slug=fact_person_slug,
                            display_name=str(fact.get("person_display_name") or fact_person_slug.replace("-", " ").title()),
                        )
                    canonical_key = str(fact["canonical_key"])
                    source_id = self._record_source(
                        conn,
                        source_repo=source_repo,
                        source_path=f"eval/personal/{canonical_key}.md",
                        title=f"personal-memory-{canonical_key}",
                        sha256=f"personal-memory-{canonical_key}",
                        parsed_text=str(fact.get("quote_text") or fact.get("summary") or ""),
                    )
                    seeded = self._ensure_fact(
                        conn,
                        consolidation=consolidation,
                        canonical_key=canonical_key,
                        payload=dict(fact.get("payload") or {}),
                        person_id=int(people[fact_person_slug]["id"]),
                        domain=str(fact["domain"]),
                        category=str(fact["category"]),
                        subcategory=str(fact.get("subcategory") or ""),
                        summary=str(fact["summary"]),
                        observed_at=str(fact.get("observed_at") or "2026-04-24T00:00:00Z"),
                        valid_from=str(fact.get("valid_from") or ""),
                        event_at=str(fact.get("event_at") or ""),
                        source_id=source_id,
                        quote_text=str(fact.get("quote_text") or fact["summary"]),
                    )
                    status = str(fact.get("status") or "active")
                    if status != "active" and seeded.get("status") != status:
                        conn.execute("UPDATE memory_facts SET status = ? WHERE id = ?", (status, int(seeded["id"])))

    def _personal_evolution_residence_facts(self, conn, *, person_id: int) -> list[dict[str, Any]]:
        rows = conn.execute(
            """
            SELECT *
            FROM memory_facts
            WHERE person_id = ? AND domain = 'biography' AND category = 'residence'
            ORDER BY id ASC
            """,
            (person_id,),
        ).fetchall()
        facts: list[dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            item["payload"] = json.loads(item.pop("payload_json") or "{}")
            facts.append(item)
        return facts

    def _reset_personal_evolution_fixture(self, conn, *, fact_repo: FactRepository) -> None:
        workspace_id = fact_repo.ensure_workspace(conn, "default")
        source_rows = conn.execute(
            """
            SELECT id
            FROM sources
            WHERE workspace_id = ?
              AND (source_path LIKE ? OR origin_uri LIKE ? OR title LIKE ?)
            """,
            (workspace_id, "%memory-evolution-eval%", "%memory-evolution-eval%", "%memory-evolution-eval%"),
        ).fetchall()
        if source_rows:
            placeholders = ",".join("?" for _ in source_rows)
            conn.execute(
                f"DELETE FROM sources WHERE id IN ({placeholders})",
                [int(row["id"]) for row in source_rows],
            )
        person_rows = conn.execute(
            "SELECT id FROM persons WHERE workspace_id = ? AND slug = ?",
            (workspace_id, "memory-evolution-eval"),
        ).fetchall()
        if person_rows:
            placeholders = ",".join("?" for _ in person_rows)
            conn.execute(
                f"DELETE FROM persons WHERE id IN ({placeholders})",
                [int(row["id"]) for row in person_rows],
            )

    def _personal_memory_evolution_report(self, project_root: Path) -> dict[str, Any]:
        settings = ensure_runtime(load_settings(project_root))
        settings.runtime.profile = "fixture"
        settings.llm.provider = "mock"
        settings.llm.model = "fixture"
        settings.llm.allow_mock_provider = True
        fact_repo = FactRepository()
        source_repo = SourceRepository()
        consolidation = ConsolidationService(fact_repository=fact_repo)
        ingest_service = IngestService(source_repository=source_repo)
        conversation_service = ConversationIngestService(fact_repository=fact_repo)
        candidate_service = CandidateService(
            extraction_service=ExtractionService.from_settings(settings, usage_tracker=self.llm_usage_tracker)
        )
        publish_service = PublishService(
            fact_repository=fact_repo,
            consolidation_service=consolidation,
        )
        slug = "memory-evolution-eval"
        display_name = "Memory Evolution Eval"
        required_checks = [
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
        ]
        checks: list[dict[str, Any]] = []

        def add_check(name: str, description: str, passed: bool, details: dict[str, Any]) -> None:
            checks.append(
                {
                    "name": name,
                    "description": description,
                    "passed": bool(passed),
                    "details": details,
                }
            )

        def publish_residence_candidates(conn, candidates: list[dict]) -> list[dict]:
            published: list[dict] = []
            for candidate in candidates:
                if candidate.get("domain") != "biography" or candidate.get("category") != "residence":
                    continue
                if candidate.get("candidate_status") == "published":
                    if candidate.get("publish_target_fact_id"):
                        published.append(
                            {
                                "candidate": candidate,
                                "fact": fact_repo.get_fact(
                                    conn,
                                    fact_id=int(candidate["publish_target_fact_id"]),
                                ),
                            }
                        )
                    continue
                if candidate.get("candidate_status") != "validated_candidate":
                    continue
                published.append(
                    publish_service.publish_candidate(
                        conn,
                        workspace_slug="default",
                        candidate_id=int(candidate["id"]),
                    )
                )
            return published

        def retrieve_residence(conn, *, query: str, temporal_mode: str) -> Any:
            return self.retrieval_service.retrieve(
                conn,
                RetrievalRequest(
                    workspace="default",
                    person_slug=slug,
                    query=query,
                    domain="biography",
                    category="residence",
                    limit=3,
                    include_fallback=False,
                    temporal_mode=temporal_mode,
                    actor=build_internal_actor(settings, actor_id="eval-runner"),
                ),
                settings=settings,
                route_name="personal_memory_evolution_eval",
            )

        try:
            with get_connection(settings.db_path) as conn:
                self._reset_personal_evolution_fixture(conn, fact_repo=fact_repo)
                person = self._person(conn, fact_repo=fact_repo, slug=slug, display_name=display_name)
                person_id = int(person["id"])
                berlin_messages = [
                    {
                        "speaker": display_name,
                        "timestamp": "2026-04-21T09:00:00Z",
                        "text": "I live in Berlin.",
                    }
                ]
                berlin_source_id, berlin_conversation_id = self._ensure_imported_conversation(
                    settings,
                    conn,
                    ingest_service=ingest_service,
                    conversation_service=conversation_service,
                    filename="memory-evolution-eval-berlin.json",
                    messages=berlin_messages,
                    conversation_uid="memory-evolution-eval-berlin",
                    title="Memory Evolution Eval Berlin",
                )
                berlin_candidates = candidate_service.extract_from_conversation(
                    conn,
                    workspace_slug="default",
                    conversation_id=berlin_conversation_id,
                )
                publish_residence_candidates(conn, berlin_candidates)
                facts_after_first_import = self._personal_evolution_residence_facts(conn, person_id=person_id)
                active_after_first_import = [fact for fact in facts_after_first_import if fact["status"] == "active"]
                berlin_fact = next(
                    (fact for fact in facts_after_first_import if fact["payload"].get("city") == "Berlin"),
                    None,
                )
                add_check(
                    "incremental_import_creates_active_fact",
                    "A first incremental conversation import should create one active residence fact.",
                    berlin_fact is not None
                    and berlin_fact["status"] == "active"
                    and len(active_after_first_import) == 1,
                    {
                        "active_count": len(active_after_first_import),
                        "cities": [fact["payload"].get("city") for fact in facts_after_first_import],
                    },
                )

                same_conversation_candidates = candidate_service.extract_from_conversation(
                    conn,
                    workspace_slug="default",
                    conversation_id=berlin_conversation_id,
                )
                publish_residence_candidates(conn, same_conversation_candidates)
                facts_after_same_conversation = self._personal_evolution_residence_facts(conn, person_id=person_id)
                active_after_same_conversation = [
                    fact for fact in facts_after_same_conversation if fact["status"] == "active"
                ]
                add_check(
                    "same_conversation_reextract_idempotent",
                    "Re-extracting an already published conversation should not demote or duplicate the active fact.",
                    len(active_after_same_conversation) == 1
                    and active_after_same_conversation[0]["payload"].get("city") == "Berlin",
                    {
                        "candidate_statuses": [candidate["candidate_status"] for candidate in same_conversation_candidates],
                        "active_count": len(active_after_same_conversation),
                        "fact_count": len(facts_after_same_conversation),
                    },
                )

                repeated_source_id, repeated_conversation_id = self._ensure_imported_conversation(
                    settings,
                    conn,
                    ingest_service=ingest_service,
                    conversation_service=conversation_service,
                    filename="memory-evolution-eval-berlin.json",
                    messages=berlin_messages,
                    conversation_uid="memory-evolution-eval-berlin",
                    title="Memory Evolution Eval Berlin",
                )
                repeated_candidates = candidate_service.extract_from_conversation(
                    conn,
                    workspace_slug="default",
                    conversation_id=repeated_conversation_id,
                )
                publish_residence_candidates(conn, repeated_candidates)
                facts_after_reimport = self._personal_evolution_residence_facts(conn, person_id=person_id)
                active_after_reimport = [fact for fact in facts_after_reimport if fact["status"] == "active"]
                add_check(
                    "same_source_reimport_no_duplicate_active_facts",
                    "Re-importing and reprocessing the same source should keep one active fact for the current value.",
                    repeated_source_id == berlin_source_id
                    and repeated_conversation_id == berlin_conversation_id
                    and len(active_after_reimport) == 1
                    and active_after_reimport[0]["payload"].get("city") == "Berlin",
                    {
                        "first_source_id": berlin_source_id,
                        "repeated_source_id": repeated_source_id,
                        "first_conversation_id": berlin_conversation_id,
                        "repeated_conversation_id": repeated_conversation_id,
                        "active_count": len(active_after_reimport),
                        "fact_count": len(facts_after_reimport),
                    },
                )

                lisbon_source_id, lisbon_conversation_id = self._ensure_imported_conversation(
                    settings,
                    conn,
                    ingest_service=ingest_service,
                    conversation_service=conversation_service,
                    filename="memory-evolution-eval-lisbon.json",
                    messages=[
                        {
                            "speaker": display_name,
                            "timestamp": "2026-04-21T12:00:00Z",
                            "text": "I moved to Lisbon.",
                        }
                    ],
                    conversation_uid="memory-evolution-eval-lisbon",
                    title="Memory Evolution Eval Lisbon",
                )
                lisbon_candidates = candidate_service.extract_from_conversation(
                    conn,
                    workspace_slug="default",
                    conversation_id=lisbon_conversation_id,
                )
                publish_residence_candidates(conn, lisbon_candidates)
                facts_after_conflict = self._personal_evolution_residence_facts(conn, person_id=person_id)
                berlin_fact = next(
                    (fact for fact in facts_after_conflict if fact["payload"].get("city") == "Berlin"),
                    None,
                )
                lisbon_fact = next(
                    (fact for fact in facts_after_conflict if fact["payload"].get("city") == "Lisbon"),
                    None,
                )
                active_after_conflict = [fact for fact in facts_after_conflict if fact["status"] == "active"]
                add_check(
                    "conflict_update_supersedes_previous_fact",
                    "A newer conflicting current-state residence should supersede the old value.",
                    berlin_fact is not None
                    and lisbon_fact is not None
                    and berlin_fact["status"] == "superseded"
                    and lisbon_fact["status"] == "active"
                    and berlin_fact["superseded_by_fact_id"] == lisbon_fact["id"]
                    and len(active_after_conflict) == 1,
                    {
                        "berlin_status": berlin_fact["status"] if berlin_fact else None,
                        "lisbon_status": lisbon_fact["status"] if lisbon_fact else None,
                        "active_count": len(active_after_conflict),
                        "lisbon_source_id": lisbon_source_id,
                    },
                )
                if berlin_fact is None or lisbon_fact is None:
                    raise RuntimeError("memory evolution fixture did not produce Berlin and Lisbon facts")

                current_after_conflict = retrieve_residence(
                    conn,
                    query="Where does Memory Evolution Eval live?",
                    temporal_mode="current",
                )
                history_after_conflict = retrieve_residence(
                    conn,
                    query="Where did Memory Evolution Eval live before Lisbon?",
                    temporal_mode="history",
                )
                add_check(
                    "current_query_returns_new_fact",
                    "Current retrieval should return the latest active value after a conflict update.",
                    bool(current_after_conflict.hits)
                    and current_after_conflict.hits[0].fact_id == int(lisbon_fact["id"])
                    and current_after_conflict.hits[0].payload.get("city") == "Lisbon",
                    {
                        "hit_fact_ids": [hit.fact_id for hit in current_after_conflict.hits],
                        "hit_cities": [hit.payload.get("city") for hit in current_after_conflict.hits],
                    },
                )
                add_check(
                    "historical_query_returns_superseded_fact",
                    "Historical retrieval should expose the superseded previous value.",
                    bool(history_after_conflict.hits)
                    and history_after_conflict.hits[0].fact_id == int(berlin_fact["id"])
                    and history_after_conflict.hits[0].status == "superseded",
                    {
                        "hit_fact_ids": [hit.fact_id for hit in history_after_conflict.hits],
                        "hit_statuses": [hit.status for hit in history_after_conflict.hits],
                        "hit_cities": [hit.payload.get("city") for hit in history_after_conflict.hits],
                    },
                )
                add_check(
                    "stale_superseded_fact_excluded_from_current",
                    "The stale superseded value should not appear in current-mode retrieval.",
                    int(berlin_fact["id"]) not in [hit.fact_id for hit in current_after_conflict.hits],
                    {
                        "stale_fact_id": int(berlin_fact["id"]),
                        "current_hit_fact_ids": [hit.fact_id for hit in current_after_conflict.hits],
                    },
                )

                consolidation.mark_deleted(
                    conn,
                    fact_id=int(lisbon_fact["id"]),
                    reason="personal memory evolution eval delete",
                )
                current_after_delete = retrieve_residence(
                    conn,
                    query="Where does Memory Evolution Eval live?",
                    temporal_mode="current",
                )
                add_check(
                    "delete_hides_fact_from_retrieval",
                    "Deleted facts should not be retrieved as current facts.",
                    int(lisbon_fact["id"]) not in [hit.fact_id for hit in current_after_delete.hits],
                    {
                        "deleted_fact_id": int(lisbon_fact["id"]),
                        "current_hit_fact_ids": [hit.fact_id for hit in current_after_delete.hits],
                    },
                )

                restored = consolidation.restore(
                    conn,
                    fact_id=int(lisbon_fact["id"]),
                    reason="personal memory evolution eval restore",
                )
                current_after_restore = retrieve_residence(
                    conn,
                    query="Where does Memory Evolution Eval live?",
                    temporal_mode="current",
                )
                add_check(
                    "restore_deleted_fact_retrievable",
                    "A restored fact should become retrievable again.",
                    restored["status"] == "active"
                    and bool(current_after_restore.hits)
                    and current_after_restore.hits[0].fact_id == int(lisbon_fact["id"]),
                    {
                        "restored_status": restored["status"],
                        "current_hit_fact_ids": [hit.fact_id for hit in current_after_restore.hits],
                    },
                )

                supersede_operation = conn.execute(
                    """
                    SELECT id
                    FROM memory_operations
                    WHERE target_fact_id = ? AND operation_type = 'superseded'
                    ORDER BY id DESC
                    LIMIT 1
                    """,
                    (int(berlin_fact["id"]),),
                ).fetchone()
                if supersede_operation is None:
                    raise RuntimeError("memory evolution fixture did not record supersede operation")
                consolidation.rollback(
                    conn,
                    operation_id=int(supersede_operation["id"]),
                    reason="personal memory evolution eval rollback",
                )
                facts_after_rollback = self._personal_evolution_residence_facts(conn, person_id=person_id)
                berlin_after_rollback = next(
                    (fact for fact in facts_after_rollback if fact["payload"].get("city") == "Berlin"),
                    None,
                )
                lisbon_after_rollback = next(
                    (fact for fact in facts_after_rollback if fact["payload"].get("city") == "Lisbon"),
                    None,
                )
                current_after_rollback = retrieve_residence(
                    conn,
                    query="Where does Memory Evolution Eval live?",
                    temporal_mode="current",
                )
                active_after_rollback = [fact for fact in facts_after_rollback if fact["status"] == "active"]
                add_check(
                    "rollback_restores_previous_active_state",
                    "Rolling back the supersede should reactivate the previous state and demote the successor.",
                    berlin_after_rollback is not None
                    and lisbon_after_rollback is not None
                    and berlin_after_rollback["status"] == "active"
                    and lisbon_after_rollback["status"] == "deleted"
                    and len(active_after_rollback) == 1
                    and bool(current_after_rollback.hits)
                    and current_after_rollback.hits[0].fact_id == int(berlin_after_rollback["id"]),
                    {
                        "berlin_status": berlin_after_rollback["status"] if berlin_after_rollback else None,
                        "lisbon_status": lisbon_after_rollback["status"] if lisbon_after_rollback else None,
                        "active_count": len(active_after_rollback),
                        "current_hit_fact_ids": [hit.fact_id for hit in current_after_rollback.hits],
                        "rollback_operation_id": int(supersede_operation["id"]),
                    },
                )
        except Exception as exc:
            add_check(
                "memory_evolution_scenario_completed",
                "The memory evolution fixture should run without runtime exceptions.",
                False,
                {"error": f"{type(exc).__name__}: {exc}"},
            )

        passed = sum(1 for item in checks if item["passed"])
        missing_required_checks = sorted(set(required_checks) - {item["name"] for item in checks})
        return {
            "ok": passed == len(checks) and not missing_required_checks,
            "total": len(checks),
            "passed": passed,
            "failed": len(checks) - passed,
            "required_checks": required_checks,
            "missing_required_checks": missing_required_checks,
            "checks": checks,
        }

    def _personal_case_result(self, *, conn, settings, eval_actor, case: dict[str, Any], route_name: str) -> dict:
        started = time.perf_counter()
        retrieval = self.retrieval_service.retrieve(
            conn,
            RetrievalRequest(
                workspace=str(case.get("workspace") or "default"),
                person_slug=str(case["person_slug"]),
                query=str(case["query"]),
                domain=case.get("domain"),
                category=case.get("domain_category"),
                limit=int(case.get("limit") or 1),
                include_fallback=True,
                temporal_mode=str(case.get("temporal_mode") or "auto"),
                actor=eval_actor,
            ),
            settings=settings,
            route_name=route_name,
        )
        latency_ms = max(0, int((time.perf_counter() - started) * 1000))
        answer = self.refusal_service.build_answer(query=str(case["query"]), retrieval_result=retrieval)
        combined_text = self._combined_case_text(answer=answer, retrieval=retrieval)
        forbidden_text = self._combined_case_text(answer=answer, retrieval=retrieval, include_answer=not answer.get("refused", False))
        evidence_count = sum(len(hit.evidence) for hit in retrieval.hits)
        answer_evidence_ids = list(answer.get("evidence_ids", []))
        failures: list[str] = []
        if bool(answer["refused"]) != bool(case["expect_refused"]):
            failures.append("refusal_mismatch")
        expected_support_level = case.get("expected_support_level")
        if expected_support_level and retrieval.support_level != expected_support_level:
            failures.append("support_level_mismatch")
        expected_evidence_count_min = int(case.get("expected_evidence_count_min") or 0)
        if expected_evidence_count_min and evidence_count < expected_evidence_count_min:
            failures.append("evidence_count_too_low")
        for value in case.get("expected_values", []):
            if str(value).lower() not in combined_text:
                failures.append(f"missing_expected_value:{value}")
        for value in case.get("forbidden_values", []):
            if str(value).lower() in forbidden_text:
                failures.append(f"forbidden_value_present:{value}")
        if not answer["refused"] and retrieval.support_level in {"supported", "partial"} and not answer_evidence_ids:
            failures.append("answer_evidence_ids_missing")
        return {
            "id": case["id"],
            "conversation_id": case.get("conversation_id"),
            "group": case["group"],
            "domain": case.get("domain"),
            "domain_category": case.get("domain_category"),
            "query": case["query"],
            "person_slug": case["person_slug"],
            "passed": not failures,
            "failures": failures,
            "refused": answer["refused"],
            "expected_refused": bool(case["expect_refused"]),
            "support_level": retrieval.support_level,
            "hit_count": len(retrieval.hits),
            "fallback_hit_count": len(retrieval.fallback_hits),
            "evidence_count": evidence_count,
            "answer_fact_ids": list(answer.get("fact_ids", [])),
            "answer_evidence_ids": answer_evidence_ids,
            "latency_ms": latency_ms,
            "answer": answer["answer"],
        }

    def _personal_pass_rate(self, *, results: list[dict], group: str) -> float:
        selected = [item for item in results if item["group"] == group]
        if not selected:
            return 0.0
        return round(sum(1 for item in selected if item["passed"]) / len(selected), 4)

    def _personal_case_pass_rate(self, *, cases: list[dict[str, Any]], results: list[dict], predicate) -> float:
        selected_ids = {str(item["id"]) for item in cases if predicate(item)}
        selected = [item for item in results if str(item["id"]) in selected_ids]
        if not selected:
            return 0.0
        return round(sum(1 for item in selected if item["passed"]) / len(selected), 4)

    def _personal_case_count(self, *, cases: list[dict[str, Any]], predicate) -> int:
        return sum(1 for item in cases if predicate(item))

    def _p1_8_private_eval_target_report(
        self,
        *,
        cases: list[dict[str, Any]],
        results: list[dict],
        metrics: dict[str, Any],
    ) -> dict[str, Any]:
        def is_core_biography(item: dict[str, Any]) -> bool:
            return item.get("domain") == "biography" and item.get("group") == "core_fact"

        def is_preference_current_state(item: dict[str, Any]) -> bool:
            return (
                item.get("domain") == "preferences"
                and item.get("domain_category") == "preference"
                and item.get("group") == "preference"
            )

        def is_social_graph(item: dict[str, Any]) -> bool:
            return item.get("domain") == "social_circle" or item.get("group") == "social_family"

        def is_work_project_tool(item: dict[str, Any]) -> bool:
            return item.get("domain") == "work" and item.get("domain_category") in {"project", "tool"}

        def is_experiences_temporal(item: dict[str, Any]) -> bool:
            return item.get("domain") == "experiences" or item.get("group") in {"temporal", "rollback_update"}

        def is_experience_single_hop(item: dict[str, Any]) -> bool:
            return item.get("domain") == "experiences" and item.get("group") == "core_fact"

        def is_multi_hop(item: dict[str, Any]) -> bool:
            return item.get("group") == "social_family"

        count_predicates = {
            "core_biography": is_core_biography,
            "preference_current_state": is_preference_current_state,
            "social_graph": is_social_graph,
            "work_project_tool": is_work_project_tool,
            "experiences_temporal": is_experiences_temporal,
            "adversarial_false_premise": lambda item: item.get("group") == "adversarial_false_premise",
            "cross_person_contamination": lambda item: item.get("group") == "cross_person_contamination",
            "update_supersession": lambda item: item.get("group") == "rollback_update",
            "multi_hop": is_multi_hop,
        }
        count_checks = {
            name: {
                "value": self._personal_case_count(cases=cases, predicate=predicate),
                "required": required,
                "ok": self._personal_case_count(cases=cases, predicate=predicate) >= required,
            }
            for name, required in self.P1_8_PRIVATE_EVAL_TARGET_COUNTS.items()
            for predicate in (count_predicates[name],)
        }
        threshold_values = {
            "overall_accuracy": metrics["overall_accuracy"],
            "core_biography_accuracy": self._personal_case_pass_rate(
                cases=cases,
                results=results,
                predicate=is_core_biography,
            ),
            "preference_current_state_accuracy": self._personal_case_pass_rate(
                cases=cases,
                results=results,
                predicate=is_preference_current_state,
            ),
            "work_project_tool_accuracy": self._personal_case_pass_rate(
                cases=cases,
                results=results,
                predicate=is_work_project_tool,
            ),
            "social_graph_accuracy": self._personal_case_pass_rate(
                cases=cases,
                results=results,
                predicate=is_social_graph,
            ),
            "experiences_single_hop_accuracy": self._personal_case_pass_rate(
                cases=cases,
                results=results,
                predicate=is_experience_single_hop,
            ),
            "temporal_accuracy": metrics["temporal_accuracy"],
            "adversarial_refusal_accuracy": metrics["adversarial_robustness"],
            "cross_person_contamination": metrics["cross_person_contamination"],
            "unsupported_personal_claims_answered_as_fact": metrics["unsupported_premise_answered_as_fact"],
        }
        zero_or_lower = {
            "cross_person_contamination",
            "unsupported_personal_claims_answered_as_fact",
        }
        threshold_checks = {
            name: {
                "value": threshold_values[name],
                "threshold": threshold,
                "ok": threshold_values[name] <= threshold if name in zero_or_lower else threshold_values[name] >= threshold,
            }
            for name, threshold in self.P1_8_PRIVATE_EVAL_THRESHOLDS.items()
        }
        missing_count_targets = [name for name, item in count_checks.items() if not item["ok"]]
        failed_thresholds = [name for name, item in threshold_checks.items() if not item["ok"]]
        all_target_counts_met = not missing_count_targets
        all_thresholds_met = not failed_thresholds
        return {
            "scope": "P1.8 private realistic eval target tracking",
            "benchmark_disclaimer": (
                "Internal private eval target report from the audit remediation plan; "
                "not paper-equivalent and not a full P1.8 closure unless ok_for_full_p1_8_claim is true."
            ),
            "target_counts": self.P1_8_PRIVATE_EVAL_TARGET_COUNTS,
            "thresholds": self.P1_8_PRIVATE_EVAL_THRESHOLDS,
            "count_checks": count_checks,
            "threshold_checks": threshold_checks,
            "missing_count_targets": missing_count_targets,
            "failed_thresholds": failed_thresholds,
            "all_target_counts_met": all_target_counts_met,
            "all_thresholds_met": all_thresholds_met,
            "ok_for_full_p1_8_claim": all_target_counts_met and all_thresholds_met,
        }

    def _p2_1_external_benchmark_report(self) -> dict[str, Any]:
        return {
            "scope": "P2.1 external LoCoMO-like benchmark tracking",
            "benchmark_disclaimer": (
                "No public/external LoCoMO benchmark was run in this artifact; "
                "internal LoCoMO-like fixtures are not paper-equivalent."
            ),
            "external_dataset": "not_run",
            "judge_protocol": "not_run",
            "compared_systems": {
                "full_context": "not_run",
                "embedding_rag": "not_run",
                "memco_structured_memory": "not_run",
            },
            "reported_dimensions": {
                "single_hop": "internal_only",
                "multi_hop": "internal_only",
                "temporal": "internal_only",
                "open_domain": "internal_only",
                "adversarial": "internal_only",
            },
            "ok_for_pdf_score_claim": False,
        }

    def _source_hard_context(self, case: dict[str, Any]) -> ExtractionContext:
        return ExtractionContext(
            text=str(case.get("source_text") or ""),
            subject_key=str(case["person_slug"]),
            subject_display=str(case["person_display_name"]),
            speaker_label=str(case["person_display_name"]),
            person_id=1,
            message_id=1,
            source_segment_id=1,
            session_id=1,
            occurred_at="2026-04-24T00:00:00Z",
        )

    def _personal_source_hard_check(self, case: dict[str, Any]) -> dict:
        check_name = str(case.get("source_hard_check") or "")
        source_text = str(case.get("source_text") or "")
        failures: list[str] = []
        if not source_text:
            failures.append("source_text_missing")
        context = self._source_hard_context(case)

        if check_name == "combined_tools_split":
            work_candidates = extract_work(context)
            tools = [
                str(candidate.get("payload", {}).get("tool") or "")
                for candidate in work_candidates
                if candidate.get("domain") == "work" and candidate.get("category") == "tool"
            ]
            seeded_tools = [
                str(fact.get("payload", {}).get("tool") or "")
                for fact in case.get("seed_facts", [])
                if fact.get("domain") == "work" and fact.get("category") == "tool"
            ]
            if tools != ["Python", "Postgres"]:
                failures.append(f"source_tools_not_split:{tools}")
            if seeded_tools != ["Python", "Postgres"]:
                failures.append(f"seed_tools_not_split:{seeded_tools}")
            if any(value.lower() == "python and postgres" for value in tools + seeded_tools):
                failures.append("combined_tool_value_present")
            if any(value.lower() == "ruby" for value in tools + seeded_tools):
                failures.append("false_tool_ruby_present")
        elif check_name == "combined_project_temporal":
            work_candidates = extract_work(context)
            project_texts = [
                " ".join(
                    str(part)
                    for part in (
                        candidate.get("payload", {}).get("project"),
                        candidate.get("summary"),
                        candidate.get("evidence", [{}])[0].get("quote") if candidate.get("evidence") else "",
                    )
                    if part
                )
                for candidate in work_candidates
                if candidate.get("domain") == "work" and candidate.get("category") == "project"
            ]
            seeded_text = " ".join(json.dumps(fact, ensure_ascii=False) for fact in case.get("seed_facts", []))
            source_combined = " ".join(project_texts).lower()
            seeded_combined = seeded_text.lower()
            if "project phoenix" not in source_combined:
                failures.append("source_project_phoenix_missing")
            if "march" not in source_combined:
                failures.append("source_project_temporal_anchor_missing")
            if "project phoenix" not in seeded_combined:
                failures.append("seed_project_phoenix_missing")
            if "march" not in seeded_combined:
                failures.append("seed_project_temporal_anchor_missing")
        elif check_name == "experience_accident_temporal":
            experience_candidates = extract_experiences(context)
            combined = " ".join(json.dumps(candidate, ensure_ascii=False) for candidate in experience_candidates).lower()
            if "serious accident" not in combined:
                failures.append("serious_accident_missing")
            if "october 2023" not in combined and "2023" not in combined:
                failures.append("accident_temporal_anchor_missing")
            if "negative" not in combined:
                failures.append("accident_negative_valence_missing")
        elif check_name == "negated_preference_not_positive":
            preference_candidates = extract_preferences(context)
            positive_sushi = [
                candidate
                for candidate in preference_candidates
                if str(candidate.get("payload", {}).get("value") or "").lower() == "sushi"
                and str(candidate.get("payload", {}).get("polarity") or "like").lower() == "like"
                and candidate.get("payload", {}).get("is_current") is not False
            ]
            if positive_sushi:
                failures.append("negated_sushi_became_positive_preference")
            if case.get("seed_facts"):
                failures.append("negated_case_seeded_positive_fact")
        elif check_name == "hypothetical_residence_not_positive":
            biography_candidates = extract_biography(context)
            experience_candidates = extract_experiences(context)
            paris_residence = [
                candidate
                for candidate in biography_candidates
                if candidate.get("domain") == "biography"
                and candidate.get("category") == "residence"
                and str(candidate.get("payload", {}).get("city") or "").lower() == "paris"
            ]
            moved_to_paris = [
                candidate
                for candidate in experience_candidates
                if "paris" in json.dumps(candidate.get("payload", {}), ensure_ascii=False).lower()
            ]
            if paris_residence or moved_to_paris:
                failures.append("hypothetical_paris_became_positive_fact")
            if case.get("seed_facts"):
                failures.append("hypothetical_case_seeded_positive_fact")
        elif check_name == "preference_update_current":
            preference_candidates = extract_preferences(context)
            current_coffee = [
                candidate
                for candidate in preference_candidates
                if str(candidate.get("payload", {}).get("value") or "").lower() == "coffee"
                and candidate.get("payload", {}).get("is_current") is not False
            ]
            current_tea = [
                candidate
                for candidate in preference_candidates
                if str(candidate.get("payload", {}).get("value") or "").lower() == "tea"
                and candidate.get("payload", {}).get("is_current") is not False
            ]
            if not current_coffee:
                failures.append("current_coffee_missing")
            if current_tea:
                failures.append("old_tea_still_current")
        else:
            failures.append(f"unknown_source_hard_check:{check_name}")

        return {
            "id": case["id"],
            "source_hard_check": check_name,
            "source_text": source_text,
            "passed": not failures,
            "failures": failures,
        }

    def _personal_source_hard_checks(self, cases: list[dict[str, Any]]) -> list[dict]:
        return [
            self._personal_source_hard_check(case)
            for case in cases
            if str(case.get("source_hard_check") or "")
        ]

    def _personal_group_counts(self, cases: list[dict[str, Any]]) -> dict[str, int]:
        return {group: sum(1 for item in cases if item["group"] == group) for group in sorted(self.PERSONAL_MEMORY_REQUIRED_COUNTS)}

    def _personal_count_checks(self, cases: list[dict[str, Any]]) -> dict[str, dict]:
        counts = self._personal_group_counts(cases)
        return {
            group: {"value": counts.get(group, 0), "required": required, "ok": counts.get(group, 0) >= required}
            for group, required in self.PERSONAL_MEMORY_REQUIRED_COUNTS.items()
        }

    def _locomo_like_suite_report(self, goldens_dir: Path, cases: list[dict[str, Any]]) -> dict[str, Any]:
        manifest_path = goldens_dir / self.LOCOMO_LIKE_MANIFEST_NAME
        fallback_disclaimer = "Internal LoCoMo-like personal-memory eval; not paper-equivalent."
        required_coverage = set(self.PERSONAL_MEMORY_COVERAGE_GROUPS)
        cases_by_conversation: dict[str, list[dict[str, Any]]] = {}
        cases_missing_conversation_id: list[str] = []
        for case in cases:
            conversation_id = str(case.get("conversation_id") or "").strip()
            if not conversation_id:
                cases_missing_conversation_id.append(str(case.get("id") or "<unknown>"))
                continue
            cases_by_conversation.setdefault(conversation_id, []).append(case)

        def empty_report(error: str) -> dict[str, Any]:
            return {
                "manifest_path": str(manifest_path),
                "benchmark_disclaimer": fallback_disclaimer,
                "eventual_target_questions": 1000,
                "conversation_count": 0,
                "required_conversation_count": self.LOCOMO_LIKE_MIN_CONVERSATIONS,
                "long_conversation_min_turns": self.LOCOMO_LIKE_DEFAULT_MIN_TURNS,
                "long_conversation_count": 0,
                "min_persons_per_conversation": 0,
                "all_conversations_have_two_or_more_persons": False,
                "linked_case_count": 0,
                "total_case_count": len(cases),
                "all_cases_linked_to_conversations": False,
                "cases_missing_conversation_id": cases_missing_conversation_id[:50],
                "case_conversation_ids_missing_from_suite": sorted(cases_by_conversation)[:50],
                "coverage_dimensions": [],
                "required_coverage_dimensions": sorted(required_coverage),
                "missing_coverage_dimensions": sorted(required_coverage),
                "conversations": [],
                "ok": False,
                "error": error,
            }

        if not manifest_path.exists():
            return empty_report("locomo_like_manifest_missing")

        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            return empty_report(f"locomo_like_manifest_invalid_json:{exc.msg}")

        conversations_file = str(manifest.get("conversations_file") or "").strip()
        if not conversations_file:
            return empty_report("locomo_like_conversations_file_missing")
        conversations_path = goldens_dir / conversations_file
        if not conversations_path.exists():
            return empty_report("locomo_like_conversations_file_not_found")
        try:
            conversations_payload = json.loads(conversations_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            return empty_report(f"locomo_like_conversations_invalid_json:{exc.msg}")
        fixtures_raw = conversations_payload.get("conversations")
        fixtures = fixtures_raw if isinstance(fixtures_raw, list) else []
        fixtures_by_id = {
            str(item.get("conversation_id")): item
            for item in fixtures
            if isinstance(item, dict) and item.get("conversation_id")
        }

        conversations_raw = manifest.get("conversations")
        conversations = conversations_raw if isinstance(conversations_raw, list) else []
        try:
            min_turns = int(manifest.get("long_conversation_min_turns") or self.LOCOMO_LIKE_DEFAULT_MIN_TURNS)
        except (TypeError, ValueError):
            min_turns = self.LOCOMO_LIKE_DEFAULT_MIN_TURNS
        try:
            eventual_target_questions = int(manifest.get("eventual_target_questions") or 1000)
        except (TypeError, ValueError):
            eventual_target_questions = 1000

        coverage_dimensions: set[str] = set()
        conversation_reports: list[dict[str, Any]] = []
        person_counts: list[int] = []
        long_conversation_count = 0
        linked_case_ids: set[str] = set()
        suite_conversation_ids: set[str] = set()

        for index, item in enumerate(conversations):
            entry = item if isinstance(item, dict) else {}
            conversation_id = str(entry.get("conversation_id") or f"conversation_{index + 1}")
            suite_conversation_ids.add(conversation_id)
            fixture = fixtures_by_id.get(conversation_id, {})
            turns_raw = fixture.get("turns", []) if isinstance(fixture, dict) else []
            turns = turns_raw if isinstance(turns_raw, list) else []
            try:
                declared_turn_count = int(entry.get("turn_count") or 0)
            except (TypeError, ValueError):
                declared_turn_count = 0
            actual_turn_count = len(turns)
            fixture_person_slugs = {
                str(person).strip()
                for person in fixture.get("person_slugs", [])
                if str(person).strip()
            } if isinstance(fixture, dict) else set()
            speaker_slugs = {
                str(turn.get("speaker_slug") or "").strip()
                for turn in turns
                if isinstance(turn, dict) and str(turn.get("speaker_slug") or "").strip()
            }
            manifest_person_slugs = {
                str(person).strip()
                for person in entry.get("person_slugs", [])
                if str(person).strip()
            }
            person_slugs = fixture_person_slugs | speaker_slugs | manifest_person_slugs
            coverage = {
                str(name).strip()
                for name in entry.get("coverage", [])
                if str(name).strip()
            }
            fixture_linked_case_ids = {
                str(case_id)
                for case_id in fixture.get("linked_case_ids", [])
            } if isinstance(fixture, dict) else set()
            actual_cases = cases_by_conversation.get(conversation_id, [])
            actual_case_ids = {str(case.get("id") or "") for case in actual_cases}
            actual_case_person_slugs = {
                str(case.get("person_slug") or "").strip()
                for case in actual_cases
                if str(case.get("person_slug") or "").strip()
            }
            linked_case_ids.update(actual_case_ids)
            coverage_dimensions.update(coverage)
            person_count = len(person_slugs)
            person_counts.append(person_count)
            long_ok = actual_turn_count >= min_turns
            persons_ok = person_count >= self.LOCOMO_LIKE_MIN_PERSONS_PER_CONVERSATION
            turns_have_required_persons = len(speaker_slugs) >= self.LOCOMO_LIKE_MIN_PERSONS_PER_CONVERSATION
            fixture_matches_cases = fixture_linked_case_ids == actual_case_ids
            cases_match_people = actual_case_person_slugs <= speaker_slugs
            if long_ok:
                long_conversation_count += 1
            conversation_reports.append(
                {
                    "conversation_id": conversation_id,
                    "declared_turn_count": declared_turn_count,
                    "turn_count": actual_turn_count,
                    "long_conversation": long_ok,
                    "person_count": person_count,
                    "persons_ok": persons_ok,
                    "speaker_count": len(speaker_slugs),
                    "turns_have_required_persons": turns_have_required_persons,
                    "linked_case_count": len(actual_case_ids),
                    "fixture_linked_case_count": len(fixture_linked_case_ids),
                    "fixture_matches_cases": fixture_matches_cases,
                    "cases_match_people": cases_match_people,
                    "coverage": sorted(coverage),
                    "ok": (
                        long_ok
                        and persons_ok
                        and turns_have_required_persons
                        and fixture_matches_cases
                        and cases_match_people
                        and bool(coverage & required_coverage)
                    ),
                }
            )

        missing_coverage = sorted(required_coverage - coverage_dimensions)
        case_conversation_ids_missing_from_suite = sorted(set(cases_by_conversation) - suite_conversation_ids)
        conversations_without_cases = sorted(
            item["conversation_id"] for item in conversation_reports if item["linked_case_count"] == 0
        )
        all_have_two_persons = bool(conversation_reports) and all(item["persons_ok"] for item in conversation_reports)
        all_turns_have_required_persons = bool(conversation_reports) and all(
            item["turns_have_required_persons"] for item in conversation_reports
        )
        all_fixtures_match_cases = bool(conversation_reports) and all(
            item["fixture_matches_cases"] for item in conversation_reports
        )
        all_cases_match_people = bool(conversation_reports) and all(
            item["cases_match_people"] for item in conversation_reports
        )
        all_cases_linked = (
            len(linked_case_ids) == len(cases)
            and not cases_missing_conversation_id
            and not case_conversation_ids_missing_from_suite
            and not conversations_without_cases
        )
        ok = (
            len(conversation_reports) >= self.LOCOMO_LIKE_MIN_CONVERSATIONS
            and long_conversation_count >= self.LOCOMO_LIKE_MIN_CONVERSATIONS
            and all_have_two_persons
            and all_turns_have_required_persons
            and all_fixtures_match_cases
            and all_cases_match_people
            and all_cases_linked
            and not missing_coverage
        )
        return {
            "manifest_path": str(manifest_path),
            "conversations_path": str(conversations_path),
            "schema_version": manifest.get("schema_version"),
            "benchmark_disclaimer": str(manifest.get("benchmark_disclaimer") or fallback_disclaimer),
            "eventual_target_questions": eventual_target_questions,
            "conversation_count": len(conversation_reports),
            "required_conversation_count": self.LOCOMO_LIKE_MIN_CONVERSATIONS,
            "long_conversation_min_turns": min_turns,
            "long_conversation_count": long_conversation_count,
            "min_persons_per_conversation": min(person_counts) if person_counts else 0,
            "all_conversations_have_two_or_more_persons": all_have_two_persons,
            "all_turns_have_two_or_more_speakers": all_turns_have_required_persons,
            "linked_case_count": len(linked_case_ids),
            "total_case_count": len(cases),
            "all_cases_linked_to_conversations": all_cases_linked,
            "cases_missing_conversation_id": cases_missing_conversation_id[:50],
            "case_conversation_ids_missing_from_suite": case_conversation_ids_missing_from_suite[:50],
            "conversations_without_cases": conversations_without_cases[:50],
            "all_fixture_case_links_match": all_fixtures_match_cases,
            "all_case_persons_present_in_turns": all_cases_match_people,
            "coverage_dimensions": sorted(coverage_dimensions),
            "required_coverage_dimensions": sorted(required_coverage),
            "missing_coverage_dimensions": missing_coverage,
            "conversations": conversation_reports,
            "ok": ok,
        }

    def _long_corpus_stress_messages(self, *, message_count: int) -> list[dict[str, Any]]:
        templates = (
            ("Stress Alice", "I live in Lisbon."),
            ("Stress Bob", "I live in Porto."),
            ("Stress Alice", "I prefer coffee."),
            ("Stress Alice", "I used to prefer tea, but now I prefer coffee."),
            ("Stress Alice", "In October 2023 I had an accident at the Grand Canyon."),
            ("Stress Alice", "I worked on Project Atlas with Stress Bob and launched it in March."),
            ("Stress Carla", "I live in Berlin."),
            ("Stress Dana", "I prefer sushi."),
            ("Stress Alice", "My sister is Stress Carla and my best friend is Stress Bob."),
            ("Stress Evan", "I attended PyCon in 2024."),
        )
        messages: list[dict[str, Any]] = []
        for index in range(max(1, message_count)):
            speaker, text = templates[index % len(templates)]
            day = (index % 28) + 1
            minute = index % 60
            messages.append(
                {
                    "role": "user",
                    "speaker": speaker,
                    "timestamp": f"2024-01-{day:02d}T10:{minute:02d}:00Z",
                    "text": text,
                    "meta": {"session_uid": f"long-corpus-stress-{index // 25:03d}"},
                }
            )
        return messages

    def _count_workspace_rows(self, conn, *, workspace_id: int, table: str) -> int:
        if table not in {"memory_facts", "fact_candidates"}:
            raise ValueError(f"Unsupported stress counter table: {table}")
        row = conn.execute(f"SELECT COUNT(*) AS count FROM {table} WHERE workspace_id = ?", (workspace_id,)).fetchone()
        return int(row["count"]) if row is not None else 0

    def _long_corpus_probe_result(self, *, conn, settings, eval_actor, probe: dict[str, Any]) -> dict[str, Any]:
        started = time.perf_counter()
        retrieval = self.retrieval_service.retrieve(
            conn,
            RetrievalRequest(
                workspace="long-corpus-stress",
                person_slug=str(probe["person_slug"]),
                query=str(probe["query"]),
                domain=probe.get("domain"),
                category=probe.get("category"),
                limit=int(probe.get("limit") or 3),
                include_fallback=True,
                temporal_mode=str(probe.get("temporal_mode") or "auto"),
                actor=eval_actor,
            ),
            settings=settings,
            route_name="long_corpus_stress",
        )
        latency_ms = max(0, int((time.perf_counter() - started) * 1000))
        answer = self.refusal_service.build_answer(query=str(probe["query"]), retrieval_result=retrieval)
        combined_text = self._combined_case_text(answer=answer, retrieval=retrieval)
        forbidden_text = self._combined_case_text(answer=answer, retrieval=retrieval, include_answer=not answer.get("refused", False))
        failures: list[str] = []
        if bool(answer["refused"]) != bool(probe["expect_refused"]):
            failures.append("refusal_mismatch")
        expected_support_level = probe.get("expected_support_level")
        if expected_support_level and retrieval.support_level != expected_support_level:
            failures.append("support_level_mismatch")
        for value in probe.get("expected_values", []):
            if str(value).lower() not in combined_text:
                failures.append(f"missing_expected_value:{value}")
        for value in probe.get("forbidden_values", []):
            if str(value).lower() in forbidden_text:
                failures.append(f"forbidden_value_present:{value}")
        return {
            "name": str(probe["name"]),
            "query": str(probe["query"]),
            "passed": not failures,
            "failures": failures,
            "refused": bool(answer["refused"]),
            "support_level": retrieval.support_level,
            "hit_count": len(retrieval.hits),
            "fallback_hit_count": len(retrieval.fallback_hits),
            "latency_ms": latency_ms,
            "answer": answer["answer"],
        }

    def _p2_3_long_corpus_target_report(
        self,
        *,
        messages: list[dict[str, Any]],
        source_types: list[str],
        person_count: int,
        extraction_accounting: dict[str, Any],
        candidates_extracted: int,
        facts_delta: int,
        probe_results: list[dict[str, Any]],
        false_positive_failures: int,
        refusal_mismatches: int,
    ) -> dict[str, Any]:
        message_count = len(messages)
        message_text = "\n".join(str(item.get("text") or "").lower() for item in messages)
        extraction_usage = extraction_accounting["production_accounting"]["by_stage"]["extraction"]
        dimension_checks = {
            "mixed_sources": {
                "value": sorted(set(source_types)),
                "required": "two_or_more_source_types",
                "ok": len(set(source_types)) >= 2,
            },
            "old_and_new_contradictions": {
                "value": "used to prefer" in message_text and "now i prefer" in message_text,
                "required": True,
                "ok": "used to prefer" in message_text and "now i prefer" in message_text,
            },
            "multiple_people": {
                "value": person_count,
                "required": 2,
                "ok": person_count >= 2,
            },
            "repeated_updates": {
                "value": sum(1 for item in messages if "used to prefer" in str(item.get("text") or "").lower()),
                "required": 2,
                "ok": sum(1 for item in messages if "used to prefer" in str(item.get("text") or "").lower()) >= 2,
            },
            "extraction_cost": {
                "value": extraction_usage["operation_count"],
                "required": "measured_nonzero",
                "ok": extraction_usage["operation_count"] > 0,
            },
            "candidate_volume": {
                "value": candidates_extracted,
                "required": "measured_nonzero",
                "ok": candidates_extracted > 0,
            },
            "fact_growth": {
                "value": facts_delta,
                "required": "measured_positive_delta",
                "ok": facts_delta > 0,
            },
            "retrieval_latency": {
                "value": self._latency_summary([int(item["latency_ms"]) for item in probe_results]),
                "required": "measured_for_probe_set",
                "ok": bool(probe_results),
            },
            "false_positive_retrieval": {
                "value": false_positive_failures,
                "required": 0,
                "ok": false_positive_failures == 0,
            },
            "refusal_quality": {
                "value": refusal_mismatches,
                "required": 0,
                "ok": refusal_mismatches == 0,
            },
        }
        volume_checks = {
            f"{target}_messages": {
                "value": message_count,
                "required": target,
                "ok": message_count >= target,
            }
            for target in self.P2_3_LONG_CORPUS_TARGET_MESSAGE_COUNTS
        }
        missing_volume_targets = [name for name, item in volume_checks.items() if not item["ok"]]
        missing_dimensions = [name for name, item in dimension_checks.items() if not item["ok"]]
        return {
            "scope": "P2.3 long-corpus audit target tracking",
            "benchmark_disclaimer": (
                "Internal synthetic stress target report; not a full P2.3 closure unless "
                "ok_for_full_p2_3_claim is true."
            ),
            "target_message_counts": list(self.P2_3_LONG_CORPUS_TARGET_MESSAGE_COUNTS),
            "required_dimensions": list(self.P2_3_LONG_CORPUS_REQUIRED_DIMENSIONS),
            "volume_checks": volume_checks,
            "dimension_checks": dimension_checks,
            "missing_volume_targets": missing_volume_targets,
            "missing_dimensions": missing_dimensions,
            "all_volume_targets_met": not missing_volume_targets,
            "all_dimensions_met": not missing_dimensions,
            "ok_for_full_p2_3_claim": not missing_volume_targets and not missing_dimensions,
        }

    def _long_corpus_stress_report(self, project_root: Path, *, message_count: int = 120) -> dict[str, Any]:
        settings = load_settings(project_root)
        if settings.is_fixture_runtime:
            settings.llm.provider = "mock"
            settings.llm.model = "fixture"
            settings.llm.allow_mock_provider = True
        workspace_slug = "long-corpus-stress"
        person_specs = (
            ("stress-alice", "Stress Alice"),
            ("stress-bob", "Stress Bob"),
            ("stress-carla", "Stress Carla"),
            ("stress-dana", "Stress Dana"),
            ("stress-evan", "Stress Evan"),
        )
        fact_repo = FactRepository()
        ingest_service = IngestService()
        conversation_service = ConversationIngestService()
        candidate_service = CandidateService(
            extraction_service=ExtractionService.from_settings(settings, usage_tracker=self.llm_usage_tracker)
        )
        publish_service = PublishService()
        messages = self._long_corpus_stress_messages(message_count=message_count)
        extraction_start_index = len(self.llm_usage_tracker.events)
        with get_connection(settings.db_path) as conn:
            workspace_id = fact_repo.ensure_workspace(conn, workspace_slug)
            for slug, display_name in person_specs:
                fact_repo.upsert_person(
                    conn,
                    workspace_slug=workspace_slug,
                    display_name=display_name,
                    slug=slug,
                    person_type="human",
                    aliases=[display_name],
                )
            facts_before = self._count_workspace_rows(conn, workspace_id=workspace_id, table="memory_facts")
            candidates_before = self._count_workspace_rows(conn, workspace_id=workspace_id, table="fact_candidates")
            imported = ingest_service.import_text(
                settings,
                conn,
                workspace_slug=workspace_slug,
                text=json.dumps(messages, ensure_ascii=False),
                title="long-corpus-stress-json",
                source_type="json",
            )
            conversation = conversation_service.import_conversation(
                settings,
                conn,
                workspace_slug=workspace_slug,
                source_id=imported.source_id,
                conversation_uid="long-corpus-stress",
                title="Long corpus stress fixture",
            )
            candidates = candidate_service.extract_from_conversation(
                conn,
                workspace_slug=workspace_slug,
                conversation_id=conversation.conversation_id,
                attribution_policy=settings.ingest.attribution_policy,
            )
            published: list[dict[str, Any]] = []
            publish_errors: list[dict[str, Any]] = []
            for candidate in candidates:
                if candidate["candidate_status"] != "validated_candidate":
                    continue
                try:
                    published.append(
                        publish_service.publish_candidate(
                            conn,
                            workspace_slug=workspace_slug,
                            candidate_id=int(candidate["id"]),
                        )
                    )
                except ValueError as exc:
                    publish_errors.append({"candidate_id": int(candidate["id"]), "error": str(exc)})
            facts_after = self._count_workspace_rows(conn, workspace_id=workspace_id, table="memory_facts")
            candidates_after = self._count_workspace_rows(conn, workspace_id=workspace_id, table="fact_candidates")
            extraction_accounting = self.llm_usage_tracker.summary(start_index=extraction_start_index)
            retrieval_start_index = len(self.llm_usage_tracker.events)
            eval_actor = build_internal_actor(settings, actor_id="eval-runner")
            probes = [
                {
                    "name": "supported_current_residence",
                    "person_slug": "stress-alice",
                    "query": "Where does Stress Alice live?",
                    "domain": "biography",
                    "category": "residence",
                    "expected_values": ["Lisbon"],
                    "forbidden_values": ["Berlin"],
                    "expect_refused": False,
                    "expected_support_level": "supported",
                },
                {
                    "name": "false_premise_cross_person_residence",
                    "person_slug": "stress-alice",
                    "query": "Does Stress Alice live in Berlin?",
                    "domain": "biography",
                    "category": "residence",
                    "expected_values": ["do not"],
                    "forbidden_values": ["yes", "Stress Alice lives in Berlin"],
                    "expect_refused": True,
                },
                {
                    "name": "experience_location",
                    "person_slug": "stress-alice",
                    "query": "Where did Stress Alice have the accident?",
                    "domain": "experiences",
                    "category": "event",
                    "expected_values": ["Grand Canyon"],
                    "expect_refused": False,
                    "expected_support_level": "supported",
                },
                {
                    "name": "work_outcome",
                    "person_slug": "stress-alice",
                    "query": "What did Stress Alice accomplish?",
                    "domain": "work",
                    "expected_values": ["Project Atlas", "launched"],
                    "expect_refused": False,
                    "expected_support_level": "supported",
                },
                {
                    "name": "social_relation",
                    "person_slug": "stress-alice",
                    "query": "Who is Stress Alice's best friend?",
                    "domain": "social_circle",
                    "expected_values": ["Stress Bob"],
                    "expect_refused": False,
                    "expected_support_level": "supported",
                },
            ]
            probe_results = [
                self._long_corpus_probe_result(
                    conn=conn,
                    settings=settings,
                    eval_actor=eval_actor,
                    probe=probe,
                )
                for probe in probes
            ]
            retrieval_accounting = self.llm_usage_tracker.summary(start_index=retrieval_start_index)
        extraction_usage = extraction_accounting["production_accounting"]["by_stage"]["extraction"]
        candidate_status_counts = {
            status: sum(1 for item in candidates if item["candidate_status"] == status)
            for status in sorted({str(item["candidate_status"]) for item in candidates})
        }
        false_positive_failures = sum(
            1
            for item in probe_results
            if any(str(failure).startswith("forbidden_value_present:") for failure in item["failures"])
        )
        refusal_mismatches = sum(1 for item in probe_results if "refusal_mismatch" in item["failures"])
        ok = (
            conversation.message_count == len(messages)
            and conversation.chunk_count > 1
            and len(candidates) > 0
            and facts_after > facts_before
            and not publish_errors
            and all(item["passed"] for item in probe_results)
            and extraction_usage["operation_count"] > 0
        )
        return {
            "scope": "internal synthetic long-corpus stress smoke",
            "benchmark_disclaimer": "Internal synthetic stress; not LoCoMo paper-equivalent and not a 50k/500k-message claim.",
            "ok": ok,
            "limits": {
                "messages_tested": len(messages),
                "full_50k_or_500k_corpus_tested": False,
                "storage_engine": settings.storage.engine,
                "runtime_profile": settings.runtime.profile,
            },
            "source_volume": {
                "source_count": 1,
                "source_types": ["json"],
                "person_count": len(person_specs),
                "message_count": conversation.message_count,
                "chunk_count": conversation.chunk_count,
                "session_count": conversation.session_count,
            },
            "candidate_volume": {
                "before": candidates_before,
                "after": candidates_after,
                "delta": candidates_after - candidates_before,
                "extracted_total": len(candidates),
                "status_counts": candidate_status_counts,
                "published_count": len(published),
                "publish_error_count": len(publish_errors),
                "publish_errors": publish_errors[:10],
            },
            "fact_growth": {
                "before": facts_before,
                "after": facts_after,
                "delta": facts_after - facts_before,
            },
            "extraction_cost": {
                "token_accounting": extraction_accounting,
                "candidate_count": extraction_accounting["production_accounting"]["amortized_extraction"]["candidate_count"],
            },
            "retrieval_probe_quality": {
                "total": len(probe_results),
                "passed": sum(1 for item in probe_results if item["passed"]),
                "false_positive_retrieval_failures": false_positive_failures,
                "refusal_mismatches": refusal_mismatches,
                "latency_ms": self._latency_summary([int(item["latency_ms"]) for item in probe_results]),
                "token_accounting": retrieval_accounting,
                "probes": probe_results,
            },
            "p2_3_target_report": self._p2_3_long_corpus_target_report(
                messages=messages,
                source_types=["json"],
                person_count=len(person_specs),
                extraction_accounting=extraction_accounting,
                candidates_extracted=len(candidates),
                facts_delta=facts_after - facts_before,
                probe_results=probe_results,
                false_positive_failures=false_positive_failures,
                refusal_mismatches=refusal_mismatches,
            ),
        }

    def _personal_metrics(
        self,
        *,
        goldens_dir: Path,
        cases: list[dict[str, Any]],
        results: list[dict],
        source_hard_checks: list[dict],
        start_event_index: int,
        long_corpus_stress: dict[str, Any],
    ) -> dict:
        unsupported_premise_answered_as_fact = sum(
            1
            for item in results
            if item["group"] == "adversarial_false_premise" and (not item["refused"] or item["support_level"] == "supported")
        )
        evidence_missing_on_supported_answers = sum(
            1
            for item in results
            if not item["refused"] and item["support_level"] in {"supported", "partial"} and not item["answer_evidence_ids"]
        )
        cross_person_contamination = sum(
            1
            for item in results
            if item["group"] == "cross_person_contamination" and any("forbidden_value_present" in failure for failure in item["failures"])
        )
        source_hard_case_failures = sum(1 for item in source_hard_checks if not item["passed"])
        metrics = {
            "overall_accuracy": round(sum(1 for item in results if item["passed"]) / len(results), 4) if results else 0.0,
            "core_memory_accuracy": self._personal_pass_rate(results=results, group="core_fact"),
            "adversarial_robustness": self._personal_pass_rate(results=results, group="adversarial_false_premise"),
            "temporal_accuracy": self._personal_case_pass_rate(
                cases=cases,
                results=results,
                predicate=lambda item: item.get("group") == "temporal",
            ),
            "cross_person_contamination": cross_person_contamination,
            "unsupported_premise_answered_as_fact": unsupported_premise_answered_as_fact,
            "evidence_missing_on_supported_answers": evidence_missing_on_supported_answers,
            "speakerless_owner_fallback_accuracy": self._personal_pass_rate(results=results, group="speakerless_note"),
            "tool_project_retrieval_pass_rate": self._personal_case_pass_rate(
                cases=cases,
                results=results,
                predicate=lambda item: item.get("scenario") == "work"
                and item.get("domain") == "work"
                and item.get("domain_category") in {"tool", "project"},
            ),
            "experience_event_retrieval_pass_rate": self._personal_case_pass_rate(
                cases=cases,
                results=results,
                predicate=lambda item: item.get("scenario") == "experiences"
                and item.get("domain") == "experiences"
                and item.get("domain_category") == "event",
            ),
            "source_hard_case_failures": source_hard_case_failures,
        }
        checks = {
            "overall_accuracy": {
                "value": metrics["overall_accuracy"],
                "threshold": self.PERSONAL_MEMORY_THRESHOLDS["overall_accuracy"],
                "ok": metrics["overall_accuracy"] >= self.PERSONAL_MEMORY_THRESHOLDS["overall_accuracy"],
            },
            "core_memory_accuracy": {
                "value": metrics["core_memory_accuracy"],
                "threshold": self.PERSONAL_MEMORY_THRESHOLDS["core_memory_accuracy"],
                "ok": metrics["core_memory_accuracy"] >= self.PERSONAL_MEMORY_THRESHOLDS["core_memory_accuracy"],
            },
            "adversarial_robustness": {
                "value": metrics["adversarial_robustness"],
                "threshold": self.PERSONAL_MEMORY_THRESHOLDS["adversarial_robustness"],
                "ok": metrics["adversarial_robustness"] >= self.PERSONAL_MEMORY_THRESHOLDS["adversarial_robustness"],
            },
            "temporal_accuracy": {
                "value": metrics["temporal_accuracy"],
                "threshold": self.PERSONAL_MEMORY_THRESHOLDS["temporal_accuracy"],
                "ok": metrics["temporal_accuracy"] >= self.PERSONAL_MEMORY_THRESHOLDS["temporal_accuracy"],
            },
            "cross_person_contamination": {
                "value": metrics["cross_person_contamination"],
                "threshold": self.PERSONAL_MEMORY_THRESHOLDS["cross_person_contamination"],
                "ok": metrics["cross_person_contamination"] <= self.PERSONAL_MEMORY_THRESHOLDS["cross_person_contamination"],
            },
            "unsupported_premise_answered_as_fact": {
                "value": metrics["unsupported_premise_answered_as_fact"],
                "threshold": self.PERSONAL_MEMORY_THRESHOLDS["unsupported_premise_answered_as_fact"],
                "ok": metrics["unsupported_premise_answered_as_fact"]
                <= self.PERSONAL_MEMORY_THRESHOLDS["unsupported_premise_answered_as_fact"],
            },
            "evidence_missing_on_supported_answers": {
                "value": metrics["evidence_missing_on_supported_answers"],
                "threshold": self.PERSONAL_MEMORY_THRESHOLDS["evidence_missing_on_supported_answers"],
                "ok": metrics["evidence_missing_on_supported_answers"]
                <= self.PERSONAL_MEMORY_THRESHOLDS["evidence_missing_on_supported_answers"],
            },
            "speakerless_owner_fallback_accuracy": {
                "value": metrics["speakerless_owner_fallback_accuracy"],
                "threshold": self.PERSONAL_MEMORY_THRESHOLDS["speakerless_owner_fallback_accuracy"],
                "ok": metrics["speakerless_owner_fallback_accuracy"]
                >= self.PERSONAL_MEMORY_THRESHOLDS["speakerless_owner_fallback_accuracy"],
            },
            "tool_project_retrieval_pass_rate": {
                "value": metrics["tool_project_retrieval_pass_rate"],
                "threshold": self.PERSONAL_MEMORY_THRESHOLDS["tool_project_retrieval_pass_rate"],
                "ok": metrics["tool_project_retrieval_pass_rate"]
                >= self.PERSONAL_MEMORY_THRESHOLDS["tool_project_retrieval_pass_rate"],
            },
            "experience_event_retrieval_pass_rate": {
                "value": metrics["experience_event_retrieval_pass_rate"],
                "threshold": self.PERSONAL_MEMORY_THRESHOLDS["experience_event_retrieval_pass_rate"],
                "ok": metrics["experience_event_retrieval_pass_rate"]
                >= self.PERSONAL_MEMORY_THRESHOLDS["experience_event_retrieval_pass_rate"],
            },
            "source_hard_case_failures": {
                "value": metrics["source_hard_case_failures"],
                "threshold": self.PERSONAL_MEMORY_THRESHOLDS["source_hard_case_failures"],
                "ok": metrics["source_hard_case_failures"]
                <= self.PERSONAL_MEMORY_THRESHOLDS["source_hard_case_failures"],
            },
        }
        count_checks = self._personal_count_checks(cases)
        group_reports = []
        for group in sorted({item["group"] for item in results}):
            selected = [item for item in results if item["group"] == group]
            group_reports.append(
                {
                    "name": group,
                    "total": len(selected),
                    "passed": sum(1 for item in selected if item["passed"]),
                    "pass_rate": self._personal_pass_rate(results=results, group=group),
                }
            )
        coverage = {}
        for name, groups in self.PERSONAL_MEMORY_COVERAGE_GROUPS.items():
            covered_cases = [item for item in results if item["group"] in groups]
            coverage[name] = {
                "groups": sorted(groups),
                "total": len(covered_cases),
                "passed": sum(1 for item in covered_cases if item["passed"]),
                "covered": bool(covered_cases),
                "pass_rate": round(sum(1 for item in covered_cases if item["passed"]) / len(covered_cases), 4)
                if covered_cases
                else 0.0,
            }
        locomo_like_suite = self._locomo_like_suite_report(goldens_dir, cases)
        count_checks.update(
            {
                "locomo_like_conversation_count": {
                    "value": locomo_like_suite["conversation_count"],
                    "required": locomo_like_suite["required_conversation_count"],
                    "ok": locomo_like_suite["conversation_count"] >= locomo_like_suite["required_conversation_count"],
                },
                "locomo_like_long_conversations": {
                    "value": locomo_like_suite["long_conversation_count"],
                    "required": locomo_like_suite["required_conversation_count"],
                    "ok": locomo_like_suite["long_conversation_count"]
                    >= locomo_like_suite["required_conversation_count"],
                },
                "locomo_like_persons_per_conversation": {
                    "value": locomo_like_suite["min_persons_per_conversation"],
                    "required": self.LOCOMO_LIKE_MIN_PERSONS_PER_CONVERSATION,
                    "ok": locomo_like_suite["all_conversations_have_two_or_more_persons"],
                },
                "locomo_like_coverage_dimensions": {
                    "value": sorted(
                        set(locomo_like_suite["required_coverage_dimensions"])
                        - set(locomo_like_suite["missing_coverage_dimensions"])
                    ),
                    "required": locomo_like_suite["required_coverage_dimensions"],
                    "ok": not locomo_like_suite["missing_coverage_dimensions"],
                },
                "locomo_like_cases_linked_to_conversations": {
                    "value": locomo_like_suite["linked_case_count"],
                    "required": locomo_like_suite["total_case_count"],
                    "ok": locomo_like_suite["all_cases_linked_to_conversations"],
                },
                "long_corpus_stress_smoke": {
                    "value": long_corpus_stress["source_volume"]["message_count"],
                    "required": long_corpus_stress["limits"]["messages_tested"],
                    "ok": bool(long_corpus_stress["ok"]),
                },
            }
        )
        latencies = [int(item["latency_ms"]) for item in results]
        return {
            "metrics": metrics,
            "policy_checks": checks,
            "dataset_count_checks": count_checks,
            "p1_8_private_eval_target_report": self._p1_8_private_eval_target_report(
                cases=cases,
                results=results,
                metrics=metrics,
            ),
            "coverage": coverage,
            "locomo_like_scope": {
                "benchmark_disclaimer": "Internal LoCoMo-like personal-memory eval; not paper-equivalent.",
                "current_questions": len(results),
                "eventual_target_questions": locomo_like_suite["eventual_target_questions"],
                "conversation_suite": locomo_like_suite,
                "private_gate_thresholds": {
                    "overall_accuracy_min": self.PERSONAL_MEMORY_THRESHOLDS["overall_accuracy"],
                    "core_memory_accuracy_min": self.PERSONAL_MEMORY_THRESHOLDS["core_memory_accuracy"],
                    "adversarial_robustness_min": self.PERSONAL_MEMORY_THRESHOLDS["adversarial_robustness"],
                    "temporal_accuracy_min": self.PERSONAL_MEMORY_THRESHOLDS["temporal_accuracy"],
                    "cross_person_contamination_max": self.PERSONAL_MEMORY_THRESHOLDS["cross_person_contamination"],
                    "unsupported_premise_answered_as_fact_max": self.PERSONAL_MEMORY_THRESHOLDS[
                        "unsupported_premise_answered_as_fact"
                    ],
                },
            },
            "p2_1_external_benchmark_report": self._p2_1_external_benchmark_report(),
            "long_corpus_stress": long_corpus_stress,
            "source_hard_checks_total": len(source_hard_checks),
            "source_hard_checks_passed": sum(1 for item in source_hard_checks if item["passed"]),
            "source_hard_checks": source_hard_checks,
            "groups": group_reports,
            "retrieval_latency_ms": self._latency_summary(latencies),
            "token_accounting": self.llm_usage_tracker.summary(start_index=start_event_index),
        }

    def run_personal_memory(self, *, project_root: Path, goldens_dir: Path) -> dict:
        cases = self._load_personal_goldens(goldens_dir)
        self._seed_personal_goldens(project_root, cases)
        settings = load_settings(project_root)
        self.llm_usage_tracker.reset()
        start_event_index = len(self.llm_usage_tracker.events)
        with get_connection(settings.db_path) as conn:
            eval_actor = build_internal_actor(settings, actor_id="eval-runner")
            results = [
                self._personal_case_result(
                    conn=conn,
                    settings=settings,
                    eval_actor=eval_actor,
                    case=case,
                    route_name="personal_memory_eval",
                )
                for case in cases
            ]
        results.sort(key=lambda item: (item["group"], item["id"]))
        long_corpus_stress = self._long_corpus_stress_report(project_root)
        memory_evolution_checks = self._personal_memory_evolution_report(project_root)
        source_hard_checks = self._personal_source_hard_checks(cases)
        summary = self._personal_metrics(
            goldens_dir=goldens_dir,
            cases=cases,
            results=results,
            source_hard_checks=source_hard_checks,
            start_event_index=start_event_index,
            long_corpus_stress=long_corpus_stress,
        )
        summary["policy_checks"]["memory_evolution_update_fidelity"] = {
            "value": memory_evolution_checks["passed"],
            "threshold": memory_evolution_checks["total"],
            "ok": memory_evolution_checks["ok"],
        }
        failures = [item for item in results if not item["passed"]]
        ok = (
            not failures
            and all(item["ok"] for item in summary["policy_checks"].values())
            and all(item["ok"] for item in summary["dataset_count_checks"].values())
        )
        return {
            "artifact_type": "personal_memory_eval_artifact",
            "release_scope": "personal-agent-memory",
            "goldens_dir": str(goldens_dir),
            "total": len(results),
            "passed": sum(1 for item in results if item["passed"]),
            "failed": len(failures),
            "ok": ok,
            **summary,
            "memory_evolution_checks": memory_evolution_checks,
            "failures": failures[:50],
            "cases": results,
        }

    def run(self, project_root: Path) -> dict:
        return self.run_acceptance(project_root)

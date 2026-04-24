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
        "core_memory_accuracy": 0.95,
        "adversarial_robustness": 0.98,
        "cross_person_contamination": 0,
        "unsupported_premise_answered_as_fact": 0,
        "evidence_missing_on_supported_answers": 0,
        "speakerless_owner_fallback_accuracy": 0.95,
    }

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
        return {
            "operation_count": max(0, after["operation_count"] - before["operation_count"]),
            "input_tokens": max(0, after["input_tokens"] - before["input_tokens"]),
            "output_tokens": max(0, after["output_tokens"] - before["output_tokens"]),
            "estimated_cost_usd": round(max(0.0, after["estimated_cost_usd"] - before["estimated_cost_usd"]), 6),
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
            "group": case["group"],
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

    def _personal_group_counts(self, cases: list[dict[str, Any]]) -> dict[str, int]:
        return {group: sum(1 for item in cases if item["group"] == group) for group in sorted(self.PERSONAL_MEMORY_REQUIRED_COUNTS)}

    def _personal_count_checks(self, cases: list[dict[str, Any]]) -> dict[str, dict]:
        counts = self._personal_group_counts(cases)
        return {
            group: {"value": counts.get(group, 0), "required": required, "ok": counts.get(group, 0) >= required}
            for group, required in self.PERSONAL_MEMORY_REQUIRED_COUNTS.items()
        }

    def _personal_metrics(self, *, cases: list[dict[str, Any]], results: list[dict], start_event_index: int) -> dict:
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
        metrics = {
            "core_memory_accuracy": self._personal_pass_rate(results=results, group="core_fact"),
            "adversarial_robustness": self._personal_pass_rate(results=results, group="adversarial_false_premise"),
            "cross_person_contamination": cross_person_contamination,
            "unsupported_premise_answered_as_fact": unsupported_premise_answered_as_fact,
            "evidence_missing_on_supported_answers": evidence_missing_on_supported_answers,
            "speakerless_owner_fallback_accuracy": self._personal_pass_rate(results=results, group="speakerless_note"),
        }
        checks = {
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
        latencies = [int(item["latency_ms"]) for item in results]
        return {
            "metrics": metrics,
            "policy_checks": checks,
            "dataset_count_checks": count_checks,
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
        summary = self._personal_metrics(cases=cases, results=results, start_event_index=start_event_index)
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
            "failures": failures[:50],
            "cases": results,
        }

    def run(self, project_root: Path) -> dict:
        return self.run_acceptance(project_root)

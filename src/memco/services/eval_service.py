from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from pathlib import Path

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
            False,
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
    BENCHMARK_SETS = {
        "internal_golden_set": {"supported_fact", "duplicate_merge"},
        "adversarial_false_premise_set": {"unsupported_premise", "partial_support"},
        "temporal_set": {"temporal_update"},
        "cross_person_contamination_set": {"cross_person_contamination"},
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
        self.retrieval_service = retrieval_service or RetrievalService()
        self.refusal_service = refusal_service or RefusalService()
        self.llm_usage_tracker = LLMUsageTracker()

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

    def _combined_case_text(self, *, answer: dict, retrieval) -> str:
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
        return " ".join([answer["answer"], summary_text, payload_text, evidence_text]).lower()

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
                for value in case.forbidden_values:
                    if value.lower() in combined_text:
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
                        "answer_evidence_ids": list(answer.get("evidence_ids", [])),
                        }
                )

            results.sort(key=lambda item: (item["group"], item["name"]))
            behavior_checks = self._behavior_checks(conn)
        return results, behavior_checks

    def _build_common_metrics(self, *, results: list[dict]) -> dict:
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
            "token_accounting": self.llm_usage_tracker.summary(),
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

    def _token_accounting_by_stage(self, *, before: dict, after: dict) -> dict[str, dict]:
        llm_usage = self._usage_delta(before["llm_usage"], after["llm_usage"])
        deterministic_usage = self._usage_delta(before["deterministic_usage"], after["deterministic_usage"])
        return {
            "extraction": {
                "status": "measured_delta",
                "input_tokens": deterministic_usage["input_tokens"] + llm_usage["input_tokens"],
                "output_tokens": deterministic_usage["output_tokens"] + llm_usage["output_tokens"],
            },
            "planner": {"status": "not_instrumented", "input_tokens": 0, "output_tokens": 0},
            "retrieval": {"status": "not_instrumented", "input_tokens": 0, "output_tokens": 0},
            "answer": {"status": "not_instrumented", "input_tokens": 0, "output_tokens": 0},
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
        results, behavior_checks = self._execute_cases(project_root, cases=self.CASES, route_name="eval")
        metrics = self._build_common_metrics(results=results)
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
        before = self.llm_usage_tracker.summary()
        results, _behavior_checks = self._execute_cases(project_root, cases=benchmark_cases, route_name="benchmark")
        metrics = self._build_common_metrics(results=results)
        benchmark_sets = self._benchmark_set_reports(results=results)
        after = self.llm_usage_tracker.summary()
        token_accounting_by_stage = self._token_accounting_by_stage(before=before, after=after)
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
            "benchmark_thresholds": {
                "core_memory_accuracy_min": 0.9,
                "adversarial_robustness_min": 0.95,
                "person_isolation_min": 0.99,
                "unsupported_premise_supported_count_max": 0,
                "positive_answers_missing_evidence_ids_max": 0,
            },
            "benchmark_cases": results,
            "benchmark_sets": benchmark_sets,
            "domain_reports": self._benchmark_domain_reports(results=results),
        }

    def run(self, project_root: Path) -> dict:
        return self.run_acceptance(project_root)

from __future__ import annotations

import hashlib
import json
import shutil
import uuid
from pathlib import Path
from time import monotonic
from typing import Any

from memco.benchmarks.backends.base import BackendAnswerResult, BackendIngestResult, MemoryBackend
from memco.config import SQLITE_FALLBACK_ENGINE, Settings, load_settings, write_settings
from memco.db import get_connection
from memco.llm import build_llm_provider
from memco.llm_usage import LLMUsageTracker
from memco.models.retrieval import ActorContext, RetrievalRequest
from memco.repositories.fact_repository import FactRepository
from memco.repositories.source_repository import SourceRepository
from memco.runtime import ensure_runtime
from memco.services.answer_service import AnswerService
from memco.services.candidate_service import CandidateService
from memco.services.conversation_ingest_service import ConversationIngestService
from memco.services.extraction_service import ExtractionService
from memco.services.publish_service import MIN_PUBLISH_CONFIDENCE, PublishService
from memco.services.retrieval_service import RetrievalService
from memco.benchmarks.models import NormalizedConversation, NormalizedQuestion
from memco.utils import slugify


def locomo_conversation_to_memco_json(conversation: NormalizedConversation) -> dict[str, Any]:
    messages = [
        {
            "session_id": turn.session_id,
            "session_datetime": turn.session_datetime,
            "session": turn.session_id,
            "speaker": turn.speaker_name,
            "speaker_key": turn.speaker_key,
            "dia_id": turn.dia_id,
            "text": turn.text,
            "meta": {
                "session_id": turn.session_id,
                "session_datetime": turn.session_datetime,
                "speaker_key": turn.speaker_key,
                "dia_id": turn.dia_id,
            },
        }
        for turn in conversation.turns
    ]
    sessions = [
        {
            "session_id": session_id,
            "session_datetime": next((turn.session_datetime for turn in conversation.turns if turn.session_id == session_id), None),
        }
        for session_id in sorted({turn.session_id for turn in conversation.turns})
    ]
    return {
        "sample_id": conversation.sample_id,
        "speaker_a": conversation.speaker_a,
        "speaker_b": conversation.speaker_b,
        "sessions": sessions,
        "messages": messages,
    }


class MemcoBenchmarkBackend(MemoryBackend):
    name = "memco"
    version = "locomo-benchmark-v1"

    def __init__(
        self,
        *,
        benchmark_mode: bool,
        auto_publish_safe_candidates: bool = True,
        runtime_base: str | Path = "var/benchmark_runtime/memco",
        run_id: str | None = None,
        workspace_slug: str = "benchmark",
        extraction_mode: str = "llm_first",
        llm_settings: Settings | None = None,
        use_llm_answer: bool = False,
        max_ingest_chunks: int | None = None,
    ):
        if auto_publish_safe_candidates and not benchmark_mode:
            raise RuntimeError("auto_publish_safe_candidates is allowed only in benchmark mode")
        self.benchmark_mode = benchmark_mode
        self.auto_publish_safe_candidates = auto_publish_safe_candidates
        self.runtime_base = Path(runtime_base)
        self.run_id = run_id or uuid.uuid4().hex
        self.workspace_slug = workspace_slug
        self.extraction_mode = extraction_mode
        self.llm_settings = llm_settings
        self.use_llm_answer = use_llm_answer
        self.max_ingest_chunks = max_ingest_chunks
        self.manual_review_used = False
        self._sample_runtime: dict[str, Path] = {}
        self._sample_settings: dict[str, Settings] = {}
        self._sample_persons: dict[str, dict[str, dict]] = {}
        self._sample_report: dict[str, dict[str, Any]] = {}
        self._usage_tracker = LLMUsageTracker()

    def reset_sample(self, sample_id: str) -> None:
        root = self.runtime_base / self.run_id / sample_id
        if root.exists():
            shutil.rmtree(root)
        self._sample_runtime[sample_id] = root
        self._sample_settings.pop(sample_id, None)
        self._sample_persons.pop(sample_id, None)
        self._sample_report.pop(sample_id, None)
        self._usage_tracker.reset()

    def ingest_conversation(self, conversation: NormalizedConversation) -> BackendIngestResult:
        started = monotonic()
        settings = self._settings_for_sample(conversation.sample_id)
        payload = locomo_conversation_to_memco_json(conversation)
        source_repo = SourceRepository()
        fact_repo = FactRepository()
        conversation_service = ConversationIngestService()
        candidate_service = CandidateService(ExtractionService.from_settings(settings, usage_tracker=self._usage_tracker))
        publish_service = PublishService()
        with get_connection(settings.db_path) as conn:
            persons = self._ensure_speaker_personas(fact_repo, conn, conversation=conversation)
            source_id = source_repo.record_source(
                conn,
                workspace_slug=self.workspace_slug,
                source_path=f"var/raw/locomo/{conversation.sample_id}.json",
                source_type="json",
                origin_uri=f"locomo://{conversation.sample_id}",
                title=f"LoCoMo {conversation.sample_id}",
                sha256=hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest(),
                parsed_text=json.dumps(payload, ensure_ascii=False),
                meta={"benchmark": "locomo", "sample_id": conversation.sample_id},
            )
            conversation_result = conversation_service.import_conversation(
                settings,
                conn,
                workspace_slug=self.workspace_slug,
                source_id=source_id,
                conversation_uid=conversation.sample_id,
                title=f"LoCoMo {conversation.sample_id}",
            )
            candidates = candidate_service.extract_from_conversation(
                conn,
                workspace_slug=self.workspace_slug,
                conversation_id=int(conversation_result.conversation_id),
                include_style=False,
                include_psychometrics=False,
                attribution_policy="strict_speaker_only",
                max_chunks=self.max_ingest_chunks,
            )
            published_count = 0
            publish_errors: list[dict[str, Any]] = []
            if self.auto_publish_safe_candidates:
                for candidate in candidates:
                    if not _safe_to_auto_publish(candidate):
                        continue
                    try:
                        publish_service.publish_candidate(
                            conn,
                            workspace_slug=self.workspace_slug,
                            candidate_id=int(candidate["id"]),
                        )
                        published_count += 1
                    except Exception as exc:
                        publish_errors.append({"candidate_id": int(candidate["id"]), "error": str(exc)})
            counts = self._counts(conn)
        pending_count = int(counts["pending_candidates_count"])
        self._sample_report[conversation.sample_id] = {
            "manual_review_used": False,
            "benchmark_auto_publish_used": bool(self.auto_publish_safe_candidates),
            "pending_candidates_count": pending_count,
            "published_facts_count": int(counts["published_facts_count"]),
            "paper_comparable": True,
            "max_ingest_chunks": self.max_ingest_chunks,
            "candidate_count": int(counts["candidate_count"]),
            "publish_errors": publish_errors,
            "runtime_root": str(settings.root),
        }
        usage = self._usage_tracker.summary()
        return BackendIngestResult(
            ok=not publish_errors,
            backend_name=self.name,
            sample_id=conversation.sample_id,
            elapsed_ms=(monotonic() - started) * 1000,
            tokens=usage,
            memory_stats={
                **self._sample_report[conversation.sample_id],
                "person_slugs": {
                    "speaker_a": persons["speaker_a"]["slug"],
                    "speaker_b": persons["speaker_b"]["slug"],
                },
            },
            error="; ".join(item["error"] for item in publish_errors) if publish_errors else None,
        )

    def answer_question(self, question: NormalizedQuestion) -> BackendAnswerResult:
        started = monotonic()
        if question.target_speaker_key not in {"speaker_a", "speaker_b"}:
            return BackendAnswerResult(
                ok=True,
                backend_name=self.name,
                sample_id=question.sample_id,
                question_id=question.question_id,
                answer="",
                elapsed_ms=(monotonic() - started) * 1000,
                support_level="skipped",
                refused=True,
                raw={"skipped": True, "skip_reason": "target_unknown", "question": question.model_dump(mode="json")},
            )
        settings = self._sample_settings[question.sample_id]
        persons = self._sample_persons[question.sample_id]
        target_person = persons[question.target_speaker_key]
        usage_start = len(self._usage_tracker.events)
        with get_connection(settings.db_path) as conn:
            retrieval_service = RetrievalService(usage_tracker=self._usage_tracker)
            answer_provider = build_llm_provider(settings) if self.use_llm_answer and self.llm_settings is not None else None
            answer_service = AnswerService(
                usage_tracker=self._usage_tracker,
                llm_provider=answer_provider,
                use_llm=answer_provider is not None,
            )
            request = RetrievalRequest(
                workspace=self.workspace_slug,
                person_slug=str(target_person["slug"]),
                query=question.question,
                detail_policy="balanced",
                actor=ActorContext(
                    actor_id="benchmark",
                    actor_type="eval",
                    allowed_person_ids=[int(target_person["id"])],
                    can_view_sensitive=True,
                ),
            )
            retrieval_started = monotonic()
            retrieval_result = retrieval_service.retrieve(conn, request, settings=settings, route_name="benchmark_locomo")
            retrieval_ms = (monotonic() - retrieval_started) * 1000
            answer_started = monotonic()
            answer_payload = answer_service.build_answer(
                query=question.question,
                retrieval_result=retrieval_result,
                detail_policy="balanced",
            )
            answer_ms = (monotonic() - answer_started) * 1000
            contamination = _cross_person_contamination_fact_ids(
                conn,
                fact_ids=[int(hit.fact_id) for hit in retrieval_result.hits],
                target_person_id=int(target_person["id"]),
            )
        evidence_ids = [str(item) for item in answer_payload.get("used_evidence_ids") or answer_payload.get("evidence_ids") or []]
        raw = {
            "manual_review_used": self.manual_review_used,
            "benchmark_auto_publish_used": self.auto_publish_safe_candidates,
            "paper_comparable": not self.manual_review_used,
            "target_person_id": int(target_person["id"]),
            "target_person_slug": str(target_person["slug"]),
            "retrieved_fact_ids": [int(hit.fact_id) for hit in retrieval_result.hits],
            "retrieved_evidence_ids": [
                int(evidence["evidence_id"])
                for hit in retrieval_result.hits
                for evidence in hit.evidence
                if evidence.get("evidence_id") is not None
            ],
            "planner_route": retrieval_result.planner.model_dump(mode="json") if retrieval_result.planner else None,
            "retrieval_latency_ms": retrieval_ms,
            "answer_latency_ms": answer_ms,
            "cross_person_contamination_fact_ids": contamination,
            "sample_report": self._sample_report.get(question.sample_id, {}),
        }
        usage = self._usage_tracker.summary(start_index=usage_start)
        return BackendAnswerResult(
            ok=not contamination,
            backend_name=self.name,
            sample_id=question.sample_id,
            question_id=question.question_id,
            answer=str(answer_payload.get("answer") or ""),
            elapsed_ms=(monotonic() - started) * 1000,
            tokens=usage,
            evidence_ids=evidence_ids,
            retrieved_context=[hit.model_dump(mode="json") for hit in retrieval_result.hits],
            support_level=str(answer_payload.get("support_level") or retrieval_result.support_level),
            refused=bool(answer_payload.get("refused")),
            raw=raw,
            error="cross_person_contamination" if contamination else None,
        )

    def _settings_for_sample(self, sample_id: str) -> Settings:
        if sample_id in self._sample_settings:
            return self._sample_settings[sample_id]
        root = self._sample_runtime.get(sample_id) or self.runtime_base / self.run_id / sample_id
        settings = load_settings(root, apply_env=False)
        settings.runtime.profile = "fixture"
        settings.storage.engine = SQLITE_FALLBACK_ENGINE
        settings.storage.contract_engine = SQLITE_FALLBACK_ENGINE
        settings.storage.database_url = ""
        if self.llm_settings is None:
            settings.llm.provider = "mock"
            settings.llm.model = "fixture"
            settings.llm.allow_mock_provider = True
        else:
            settings.llm.provider = self.llm_settings.llm.provider
            settings.llm.model = self.llm_settings.llm.model
            settings.llm.base_url = self.llm_settings.llm.base_url
            settings.llm.api_key = self.llm_settings.llm.api_key
            settings.llm.allow_mock_provider = False
        settings.extraction.mode = self.extraction_mode  # type: ignore[assignment]
        settings.api.require_actor_scope = False
        settings.logging.enable_retrieval_logs = True
        write_settings(settings)
        ensure_runtime(settings)
        self._sample_settings[sample_id] = settings
        return settings

    def _ensure_speaker_personas(self, fact_repo: FactRepository, conn, *, conversation: NormalizedConversation) -> dict[str, dict]:
        persons = {
            "speaker_a": fact_repo.upsert_person(
                conn,
                workspace_slug=self.workspace_slug,
                display_name=conversation.speaker_a,
                slug=f"{conversation.sample_id}_speaker_a",
                person_type="human",
                aliases=[conversation.speaker_a],
            ),
            "speaker_b": fact_repo.upsert_person(
                conn,
                workspace_slug=self.workspace_slug,
                display_name=conversation.speaker_b,
                slug=f"{conversation.sample_id}_speaker_b",
                person_type="human",
                aliases=[conversation.speaker_b],
            ),
        }
        self._sample_persons[conversation.sample_id] = persons
        return persons

    def _counts(self, conn) -> dict[str, int]:
        candidate_count = int(conn.execute("SELECT COUNT(*) AS n FROM fact_candidates").fetchone()["n"])
        pending_count = int(
            conn.execute(
                "SELECT COUNT(*) AS n FROM fact_candidates WHERE candidate_status != 'published'"
            ).fetchone()["n"]
        )
        published_facts_count = int(conn.execute("SELECT COUNT(*) AS n FROM memory_facts WHERE status = 'active'").fetchone()["n"])
        return {
            "candidate_count": candidate_count,
            "pending_candidates_count": pending_count,
            "published_facts_count": published_facts_count,
        }


def _safe_to_auto_publish(candidate: dict[str, Any]) -> bool:
    if candidate.get("candidate_status") != "validated_candidate":
        return False
    if candidate.get("person_id") is None:
        return False
    if not candidate.get("domain") or not candidate.get("category"):
        return False
    if candidate.get("domain") == "psychometrics":
        return False
    if float(candidate.get("confidence") or 0.0) < MIN_PUBLISH_CONFIDENCE:
        return False
    evidence = candidate.get("evidence") or []
    if not evidence:
        return False
    primary = evidence[0]
    if not (primary.get("quote") or primary.get("quote_text")):
        return False
    if not (primary.get("source_segment_ids") or []):
        return False
    return True


def _cross_person_contamination_fact_ids(conn, *, fact_ids: list[int], target_person_id: int) -> list[int]:
    contaminated: list[int] = []
    for fact_id in fact_ids:
        row = conn.execute("SELECT person_id FROM memory_facts WHERE id = ?", (fact_id,)).fetchone()
        if row is not None and int(row["person_id"]) != target_person_id:
            contaminated.append(fact_id)
    return contaminated

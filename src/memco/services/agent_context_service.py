from __future__ import annotations

from memco.models.agent import AgentMemoryContextRequest
from memco.models.retrieval import RetrievalHit, RetrievalRequest
from memco.services.retrieval_service import RetrievalService


AGENT_MEMORY_CONTEXT_INSTRUCTIONS = [
    "Use only memory_context facts for personal claims.",
    "If a required fact is absent, say unknown.",
    "Do not infer private personal details beyond the returned facts and evidence.",
]


class AgentContextService:
    def __init__(self, *, retrieval_service: RetrievalService | None = None) -> None:
        self.retrieval_service = retrieval_service or RetrievalService()

    def _memory_context_item(self, hit: RetrievalHit, *, include_evidence: bool) -> dict:
        item = {
            "fact_id": hit.fact_id,
            "domain": hit.domain,
            "category": hit.category,
            "summary": hit.summary,
            "status": hit.status,
            "confidence": hit.confidence,
            "observed_at": hit.observed_at,
            "valid_from": hit.valid_from,
            "valid_to": hit.valid_to,
            "event_at": hit.event_at,
        }
        if include_evidence:
            item["evidence"] = hit.evidence
        return item

    def memory_context(self, conn, request: AgentMemoryContextRequest, *, settings, actor) -> dict:
        retrieval_request = RetrievalRequest(
            workspace=request.workspace,
            person_slug=request.person_slug,
            query=request.query,
            limit=request.max_facts,
            include_fallback=False,
            temporal_mode=request.temporal_mode,
            detail_policy="balanced",
            actor=actor,
        )
        retrieval_result = self.retrieval_service.retrieve(
            conn,
            retrieval_request,
            settings=settings,
            route_name="agent_memory_context",
        )
        return {
            "mode": request.mode,
            "query": request.query,
            "person_slug": request.person_slug,
            "answerable": retrieval_result.answerable,
            "support_level": retrieval_result.support_level,
            "refusal_category": retrieval_result.refusal_category,
            "unsupported_claims": retrieval_result.unsupported_claims,
            "memory_context": [
                self._memory_context_item(hit, include_evidence=request.include_evidence)
                for hit in retrieval_result.hits[: request.max_facts]
            ],
            "instructions_for_agent": AGENT_MEMORY_CONTEXT_INSTRUCTIONS,
            "must_not_use_as_fact": retrieval_result.must_not_use_as_fact,
        }

from __future__ import annotations

import hashlib
import time

from memco.repositories.retrieval_log_repository import RetrievalLogRepository
from memco.models.retrieval import RetrievalHit, RetrievalPlan, RetrievalRequest, RetrievalResult
from memco.repositories.fact_repository import FactRepository
from memco.repositories.retrieval_repository import RetrievalRepository
from memco.services.planner_service import PlannerService


class RetrievalService:
    def __init__(
        self,
        retrieval_repository: RetrievalRepository | None = None,
        fact_repository: FactRepository | None = None,
        retrieval_log_repository: RetrievalLogRepository | None = None,
        planner_service: PlannerService | None = None,
    ) -> None:
        self.retrieval_repository = retrieval_repository or RetrievalRepository()
        self.fact_repository = fact_repository or FactRepository()
        self.retrieval_log_repository = retrieval_log_repository or RetrievalLogRepository()
        self.planner_service = planner_service or PlannerService()

    def _hash_query(self, *, query: str, salt: str) -> str:
        return hashlib.sha256(f"{salt}:{query}".encode("utf-8")).hexdigest()

    def _write_log(self, conn, *, payload: RetrievalRequest, person_id: int | None, result: RetrievalResult, route_name: str, latency_ms: int, settings) -> None:
        if settings is None or not settings.logging.enable_retrieval_logs:
            return
        self.retrieval_log_repository.create_log(
            conn,
            workspace_slug=payload.workspace,
            person_id=person_id,
            route_name=route_name,
            query_hash=self._hash_query(query=payload.query, salt=settings.logging.query_hash_salt),
            query_length=len(payload.query),
            domain_filter="::".join(
                part
                for part in [
                    payload.domain or "",
                    payload.category or "",
                    getattr(result.planner, "temporal_mode", ""),
                ]
                if part
            ),
            fact_hit_count=len(result.hits),
            fallback_hit_count=len(result.fallback_hits),
            unsupported_premise_detected=result.unsupported_premise_detected,
            fact_ids=[hit.fact_id for hit in result.hits],
            fallback_refs=[
                {"chunk_kind": hit.chunk_kind, "chunk_id": hit.chunk_id, "source_id": hit.source_id, "score": hit.score}
                for hit in result.fallback_hits
            ],
            latency_ms=latency_ms,
        )

    def _empty_result(
        self,
        *,
        query: str,
        planner: RetrievalPlan,
        reason: str = "",
    ) -> RetrievalResult:
        unsupported_claims = [reason] if reason else []
        return RetrievalResult(
            query=query,
            unsupported_premise_detected=True,
            support_level="none",
            unsupported_claims=unsupported_claims,
            hits=[],
            planner=planner,
        )

    def retrieve(self, conn, payload: RetrievalRequest, *, settings=None, route_name: str = "retrieve") -> RetrievalResult:
        started = time.perf_counter()
        person_id = payload.person_id
        planner = self.planner_service.plan(payload)
        actor = payload.actor
        if person_id is None:
            try:
                person_id = self.fact_repository.resolve_person_id(
                    conn,
                    workspace_slug=payload.workspace,
                    person_slug=payload.person_slug,
                )
            except ValueError:
                result = RetrievalResult(
                    query=payload.query,
                    unsupported_premise_detected=True,
                    support_level="none",
                    unsupported_claims=["Unknown person."],
                    hits=[],
                    planner=planner,
                )
                self._write_log(
                    conn,
                    payload=payload,
                    person_id=None,
                    result=result,
                    route_name=route_name,
                    latency_ms=max(0, int((time.perf_counter() - started) * 1000)),
                    settings=settings,
                )
                return result
        if actor is not None and actor.allowed_person_ids and person_id not in actor.allowed_person_ids:
            result = self._empty_result(
                query=payload.query,
                planner=planner,
                reason="Actor scope prevents answering this request.",
            )
            self._write_log(
                conn,
                payload=payload,
                person_id=person_id,
                result=result,
                route_name=route_name,
                latency_ms=max(0, int((time.perf_counter() - started) * 1000)),
                settings=settings,
            )
            return result
        domain_queries = planner.domain_queries
        if actor is not None and actor.allowed_domains:
            domain_queries = [
                domain_query
                for domain_query in domain_queries
                if domain_query.domain in set(actor.allowed_domains)
            ]
            planner = planner.model_copy(
                update={
                    "domain_queries": domain_queries,
                    "requires_cross_domain_synthesis": len({item.domain for item in domain_queries}) > 1,
                }
            )
            if not domain_queries:
                result = self._empty_result(
                    query=payload.query,
                    planner=planner,
                    reason="Actor scope prevents answering this request.",
                )
                self._write_log(
                    conn,
                    payload=payload,
                    person_id=person_id,
                    result=result,
                    route_name=route_name,
                    latency_ms=max(0, int((time.perf_counter() - started) * 1000)),
                    settings=settings,
                )
                return result
        raw_hits: list[dict] = []
        for domain_query in domain_queries:
            if not domain_query.domain or domain_query.domain == "unknown":
                continue
            raw_hits.extend(
                self.retrieval_repository.retrieve_facts(
                    conn,
                    workspace_slug=payload.workspace,
                    person_id=person_id,
                    query=payload.query,
                    domain=domain_query.domain,
                    category=domain_query.category,
                    temporal_mode=planner.temporal_mode,
                    limit=payload.limit,
                )
            )
        deduped_hits: list[dict] = []
        seen_fact_ids: set[int] = set()
        for hit in sorted(raw_hits, key=lambda item: (-item["score"], -item["confidence"], item["fact_id"])):
            if int(hit["fact_id"]) in seen_fact_ids:
                continue
            seen_fact_ids.add(int(hit["fact_id"]))
            deduped_hits.append(hit)
        if planner.temporal_mode == "history":
            historical_hits = [hit for hit in deduped_hits if hit.get("status") == "superseded"]
            if historical_hits:
                deduped_hits = historical_hits
        hits = deduped_hits[: payload.limit]
        fallback_hits = []
        if not hits and payload.include_fallback:
            fallback_hits = self.retrieval_repository.retrieve_fallback_chunks(
                conn,
                workspace_slug=payload.workspace,
                person_id=person_id,
                query=payload.query,
                limit=min(payload.limit, 5),
            )
        unsupported_claims = self._detect_unsupported_claims(planner=planner, hits=hits)
        support_level = self._support_level(hits=hits, unsupported_claims=unsupported_claims)
        unsupported_flag = support_level == "none" or bool(unsupported_claims)
        result = RetrievalResult(
            query=payload.query,
            unsupported_premise_detected=unsupported_flag,
            support_level=support_level,
            unsupported_claims=unsupported_claims,
            hits=[RetrievalHit.model_validate(hit) for hit in hits],
            fallback_hits=fallback_hits,
            planner=planner,
        )
        self._write_log(
            conn,
            payload=payload,
            person_id=person_id,
            result=result,
            route_name=route_name,
            latency_ms=max(0, int((time.perf_counter() - started) * 1000)),
            settings=settings,
        )
        return result

    def _detect_unsupported_claims(self, *, planner: RetrievalPlan, hits: list[dict]) -> list[str]:
        if not planner.claim_checks:
            return []
        haystacks = []
        for hit in hits:
            payload_values = " ".join(str(value) for value in hit.get("payload", {}).values())
            haystacks.append(f"{hit.get('summary', '')} {payload_values}".lower())
        unsupported: list[str] = []
        for check in planner.claim_checks:
            needle = check.value.lower()
            if any(needle in haystack for haystack in haystacks):
                continue
            if check.claim_type == "relation":
                unsupported.append(f"No evidence that this relationship claim is supported: {check.value}.")
            elif check.claim_type == "name":
                unsupported.append(f"No evidence for named entity in the premise: {check.value}.")
            else:
                unsupported.append(f"No evidence for claim: {check.value}.")
        return unsupported

    def _support_level(self, *, hits: list[dict], unsupported_claims: list[str]) -> str:
        if hits and unsupported_claims:
            return "partial"
        if hits:
            return "full"
        return "none"

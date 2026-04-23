from __future__ import annotations

import hashlib
import json
import re
import time

from memco.llm_usage import LLMUsageEvent, LLMUsageTracker, estimate_token_count
from memco.repositories.retrieval_log_repository import RetrievalLogRepository
from memco.models.retrieval import DetailPolicy, RetrievalHit, RetrievalPlan, RetrievalRequest, RetrievalResult
from memco.repositories.fact_repository import FactRepository
from memco.repositories.retrieval_repository import RetrievalRepository
from memco.services.planner_service import PlannerService


EXPLICIT_SUBJECT_PATTERNS = (
    re.compile(
        r"^\s*(?:(?i:where|what|when|why|how))\s+(?:(?i:does|did|is|was|can|could|will|would))\s+([A-Z][A-Za-z]+(?:\s+[A-Z][A-Za-z]+)*)\b",
    ),
    re.compile(
        r"^\s*(?:(?i:does|did|is|was|can|could|will|would))\s+([A-Z][A-Za-z]+(?:\s+[A-Z][A-Za-z]+)*)\b",
    ),
    re.compile(r"^\s*(?:(?i:who))\s+(?:(?i:is))\s+([A-Z][A-Za-z]+(?:\s+[A-Z][A-Za-z]+)*)\b"),
    re.compile(r"^\s*(?:(?i:tell me about|describe|show me))\s+([A-Z][A-Za-z]+(?:\s+[A-Z][A-Za-z]+)*)\b"),
)


class RetrievalService:
    NON_FACTUAL_DOMAINS = {"style", "psychometrics"}
    RESIDENCE_FIELDS = ("city", "place")
    ORG_FIELDS = ("org",)
    PREFERENCE_FIELDS = ("value",)
    EVENT_FIELDS = ("event",)

    def __init__(
        self,
        retrieval_repository: RetrievalRepository | None = None,
        fact_repository: FactRepository | None = None,
        retrieval_log_repository: RetrievalLogRepository | None = None,
        planner_service: PlannerService | None = None,
        usage_tracker: LLMUsageTracker | None = None,
    ) -> None:
        self.retrieval_repository = retrieval_repository or RetrievalRepository()
        self.fact_repository = fact_repository or FactRepository()
        self.retrieval_log_repository = retrieval_log_repository or RetrievalLogRepository()
        self.usage_tracker = usage_tracker
        self.planner_service = planner_service or PlannerService(usage_tracker=usage_tracker)

    def _record_usage(self, *, query: str, result: RetrievalResult) -> None:
        if self.usage_tracker is None:
            return
        output = json.dumps(
            {
                "support_level": result.support_level,
                "hit_count": len(result.hits),
                "fallback_hit_count": len(result.fallback_hits),
                "unsupported_claims": result.unsupported_claims,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
        self.usage_tracker.record(
            LLMUsageEvent(
                provider="deterministic",
                model="rule-based-retrieval",
                operation="retrieve",
                input_tokens=estimate_token_count(query),
                output_tokens=estimate_token_count(output),
                estimated_cost_usd=0.0,
                deterministic=True,
                metadata={"stage": "retrieval"},
            )
        )

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
        detail_policy: DetailPolicy,
        reason: str = "",
    ) -> RetrievalResult:
        unsupported_claims = [reason] if reason else []
        return RetrievalResult(
            query=query,
            unsupported_premise_detected=True,
            support_level="unsupported",
            detail_policy=detail_policy,
            unsupported_claims=unsupported_claims,
            hits=[],
            planner=planner,
        )

    def _present_hit(self, hit: RetrievalHit, *, detail_policy: DetailPolicy) -> dict:
        if detail_policy == "core_only":
            return {
                "fact_id": hit.fact_id,
                "domain": hit.domain,
                "category": hit.category,
                "summary": hit.summary,
                "status": hit.status,
                "confidence": hit.confidence,
            }
        return hit.model_dump(mode="json")

    def present_result(self, result: RetrievalResult, *, detail_policy: DetailPolicy | None = None) -> dict:
        policy = detail_policy or result.detail_policy
        payload = result.model_dump(mode="json")
        payload["detail_policy"] = policy
        payload["hits"] = [self._present_hit(hit, detail_policy=policy) for hit in result.hits]
        return payload

    def _actor_can_view_sensitive(self, actor) -> bool:
        if actor is None:
            return True
        if actor.actor_type in {"owner", "system"}:
            return bool(actor.can_view_sensitive)
        return False

    def _filter_sensitive_hits(self, *, actor, hits: list[dict]) -> list[dict]:
        if self._actor_can_view_sensitive(actor):
            return hits
        filtered: list[dict] = []
        for hit in hits:
            if hit.get("visibility") == "owner_only" or hit.get("sensitivity") == "high":
                continue
            filtered.append(hit)
        return filtered

    def _normalize_person_label(self, value: str) -> str:
        return " ".join((value or "").replace("-", " ").strip().lower().split())

    def _extract_explicit_subjects(self, query: str) -> list[str]:
        subjects: list[str] = []
        seen: set[str] = set()
        for pattern in EXPLICIT_SUBJECT_PATTERNS:
            match = pattern.search(query)
            if match is None:
                continue
            subject = " ".join(match.group(1).strip().split())
            normalized = self._normalize_person_label(subject)
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            subjects.append(subject)
        return subjects

    def _target_person_labels(self, person: dict) -> set[str]:
        labels = {
            self._normalize_person_label(str(person.get("display_name") or "")),
            self._normalize_person_label(str(person.get("slug") or "")),
        }
        for alias in person.get("aliases", []):
            labels.add(self._normalize_person_label(str(alias.get("alias") or "")))
        return {label for label in labels if label}

    def _subject_mismatch_reason(self, *, query: str, person: dict | None, planner: RetrievalPlan) -> str:
        if person is None:
            return ""
        if any(domain_query.domain == "social_circle" for domain_query in planner.domain_queries):
            return ""
        subjects = self._extract_explicit_subjects(query)
        if not subjects:
            return ""
        target_labels = self._target_person_labels(person)
        if any(self._normalize_person_label(subject) in target_labels for subject in subjects):
            return ""
        return "Query subject does not match requested person."

    def retrieve(self, conn, payload: RetrievalRequest, *, settings=None, route_name: str = "retrieve") -> RetrievalResult:
        started = time.perf_counter()
        person_id = payload.person_id
        planner = self.planner_service.plan(payload)
        actor = payload.actor
        if settings is not None and actor is None:
            result = self._empty_result(
                query=payload.query,
                planner=planner,
                detail_policy=payload.detail_policy,
                reason="Actor context is required.",
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
            self._record_usage(query=payload.query, result=result)
            return result
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
                    support_level="unsupported",
                    detail_policy=payload.detail_policy,
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
                self._record_usage(query=payload.query, result=result)
                return result
        person = self.fact_repository.get_person(
            conn,
            workspace_slug=payload.workspace,
            person_id=person_id,
        )
        subject_mismatch_reason = self._subject_mismatch_reason(query=payload.query, person=person, planner=planner)
        if subject_mismatch_reason:
            result = self._empty_result(
                query=payload.query,
                planner=planner,
                detail_policy=payload.detail_policy,
                reason=subject_mismatch_reason,
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
            self._record_usage(query=payload.query, result=result)
            return result
        if actor is not None and actor.allowed_person_ids and person_id not in actor.allowed_person_ids:
            result = self._empty_result(
                query=payload.query,
                planner=planner,
                detail_policy=payload.detail_policy,
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
            self._record_usage(query=payload.query, result=result)
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
                    detail_policy=payload.detail_policy,
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
                self._record_usage(query=payload.query, result=result)
                return result
        raw_hits: list[dict] = []
        for domain_query in domain_queries:
            if not domain_query.domain or domain_query.domain == "unknown":
                continue
            if domain_query.domain in self.NON_FACTUAL_DOMAINS:
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
        deduped_hits = self._filter_sensitive_hits(actor=actor, hits=deduped_hits)
        if planner.temporal_mode == "history":
            historical_hits = [hit for hit in deduped_hits if hit.get("status") == "superseded"]
            if historical_hits:
                deduped_hits = historical_hits
        hits = deduped_hits[: payload.limit]
        fallback_hits = []
        requested_only_non_factual = bool(payload.domain) and payload.domain in self.NON_FACTUAL_DOMAINS
        if not hits and payload.include_fallback and not requested_only_non_factual and self._actor_can_view_sensitive(actor):
            fallback_hits = self.retrieval_repository.retrieve_fallback_chunks(
                conn,
                workspace_slug=payload.workspace,
                person_id=person_id,
                query=payload.query,
                limit=min(payload.limit, 5),
            )
        unsupported_checks = self._unsupported_checks(planner=planner, hits=hits)
        temporal_conflict_reason = self._temporal_conflict_reason(hits=hits) if planner.temporal_mode == "when" else ""
        unsupported_claims = self._detect_unsupported_claims(unsupported_checks=unsupported_checks)
        if temporal_conflict_reason:
            unsupported_claims.append(temporal_conflict_reason)
        support_level = self._support_level(
            planner=planner,
            hits=hits,
            fallback_hits=fallback_hits,
            unsupported_checks=unsupported_checks,
        )
        unsupported_flag = support_level in {"unsupported", "ambiguous", "contradicted"} or bool(unsupported_checks)
        if temporal_conflict_reason:
            unsupported_flag = True
        result = RetrievalResult(
            query=payload.query,
            unsupported_premise_detected=unsupported_flag,
            support_level=support_level,
            detail_policy=payload.detail_policy,
            unsupported_claims=unsupported_claims,
            hits=[
                RetrievalHit.model_validate(
                    {key: value for key, value in hit.items() if key not in {"sensitivity", "visibility"}}
                )
                for hit in hits
            ],
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
        self._record_usage(query=payload.query, result=result)
        return result

    def _hit_haystacks(self, *, hits: list[dict]) -> list[str]:
        haystacks = []
        for hit in hits:
            payload_values = " ".join(str(value) for value in hit.get("payload", {}).values())
            temporal_values = " ".join(
                str(hit.get(field) or "")
                for field in ("observed_at", "valid_from", "valid_to", "event_at")
            )
            haystacks.append(f"{hit.get('summary', '')} {payload_values} {temporal_values}".lower())
        return haystacks

    def _unsupported_checks(self, *, planner: RetrievalPlan, hits: list[dict]) -> list:
        if not planner.claim_checks:
            return []
        haystacks = self._hit_haystacks(hits=hits)
        unsupported = []
        for check in planner.claim_checks:
            needle = check.value.lower()
            if any(needle in haystack for haystack in haystacks):
                continue
            unsupported.append(check)
        return unsupported

    def _detect_unsupported_claims(self, *, unsupported_checks: list) -> list[str]:
        claims: list[str] = []
        for check in unsupported_checks:
            if check.claim_type == "relation":
                claims.append(f"No evidence that this relationship claim is supported: {check.value}.")
            elif check.claim_type == "name":
                claims.append(f"No evidence for named entity in the premise: {check.value}.")
            elif check.claim_type == "relation_target":
                claims.append(f"No evidence for related person in the premise: {check.value}.")
            elif check.claim_type == "employer":
                claims.append(f"No evidence for employer claim: {check.value}.")
            elif check.claim_type == "location":
                claims.append(f"No evidence for location claim: {check.value}.")
            elif check.claim_type == "preference":
                claims.append(f"No evidence for preference claim: {check.value}.")
            elif check.claim_type == "event":
                claims.append(f"No evidence for event claim: {check.value}.")
            elif check.claim_type == "date":
                claims.append(f"No evidence for date claim: {check.value}.")
            else:
                claims.append(f"No evidence for claim: {check.value}.")
        return claims

    def _normalized_values(self, *, hits: list[dict], category: str, fields: tuple[str, ...]) -> set[str]:
        values: set[str] = set()
        for hit in hits:
            if hit.get("category") != category:
                continue
            payload = hit.get("payload", {})
            for field in fields:
                value = payload.get(field)
                if value is None:
                    continue
                values.add(self._normalize_person_label(str(value)))
        return values

    def _event_year_values(self, *, hits: list[dict]) -> set[str]:
        values: set[str] = set()
        for hit in hits:
            if hit.get("category") != "event":
                continue
            payload = hit.get("payload", {})
            for field in ("temporal_anchor", "event_at"):
                value = payload.get(field)
                if value:
                    values.add(self._normalize_person_label(str(value)))
            for field in ("observed_at", "valid_from", "valid_to"):
                value = str(hit.get(field) or "")
                if len(value) >= 4 and value[:4].isdigit():
                    values.add(value[:4])
        return values

    def _is_contradicted(self, *, planner: RetrievalPlan, hits: list[dict], unsupported_checks: list) -> bool:
        if not hits or not unsupported_checks or len(planner.domain_queries) != 1:
            return False
        domain_query = planner.domain_queries[0]
        if domain_query.domain == "biography" and domain_query.category == "residence":
            supported_values = self._normalized_values(hits=hits, category="residence", fields=self.RESIDENCE_FIELDS)
            return bool(
                supported_values
                and any(
                    check.claim_type in {"name", "location"} and self._normalize_person_label(check.value) not in supported_values
                    for check in unsupported_checks
                )
            )
        if domain_query.domain == "work":
            supported_orgs = self._normalized_values(hits=hits, category="org", fields=self.ORG_FIELDS)
            return bool(
                supported_orgs
                and any(
                    check.claim_type == "employer" and self._normalize_person_label(check.value) not in supported_orgs
                    for check in unsupported_checks
                )
            )
        if domain_query.domain == "preferences" and domain_query.category == "preference":
            supported_preferences = self._normalized_values(hits=hits, category="preference", fields=self.PREFERENCE_FIELDS)
            return bool(
                supported_preferences
                and any(
                    check.claim_type == "preference" and self._normalize_person_label(check.value) not in supported_preferences
                    for check in unsupported_checks
                )
            )
        if domain_query.domain == "experiences" and domain_query.category == "event":
            supported_events = self._normalized_values(hits=hits, category="event", fields=self.EVENT_FIELDS)
            if supported_events and any(
                check.claim_type == "event" and self._normalize_person_label(check.value) not in supported_events
                for check in unsupported_checks
            ):
                return True
            supported_years = self._event_year_values(hits=hits)
            if supported_years and any(
                check.claim_type == "date" and self._normalize_person_label(check.value) not in supported_years
                for check in unsupported_checks
            ):
                return True
            return False
        if domain_query.domain == "social_circle":
            target_checks = {
                self._normalize_person_label(check.value)
                for check in planner.claim_checks
                if check.claim_type == "relation_target"
            }
            relation_checks = {
                self._normalize_person_label(check.value)
                for check in unsupported_checks
                if check.claim_type == "relation"
            }
            if not target_checks or not relation_checks:
                return False
            for hit in hits:
                payload = hit.get("payload", {})
                target_label = self._normalize_person_label(str(payload.get("target_label") or ""))
                relation = self._normalize_person_label(str(payload.get("relation") or hit.get("category") or ""))
                if target_label in target_checks and relation and relation not in relation_checks:
                    return True
        return False

    def _support_level(self, *, planner: RetrievalPlan, hits: list[dict], fallback_hits: list[dict], unsupported_checks: list) -> str:
        if planner.temporal_mode == "when":
            temporal_conflict_reason = self._temporal_conflict_reason(hits=hits)
            if temporal_conflict_reason:
                return "ambiguous"
        if hits and self._is_contradicted(planner=planner, hits=hits, unsupported_checks=unsupported_checks):
            return "contradicted"
        if hits and unsupported_checks:
            return "partial"
        if hits:
            return "supported"
        if fallback_hits:
            return "ambiguous"
        return "unsupported"

    def _temporal_conflict_reason(self, *, hits: list[dict]) -> str:
        event_dates = {str(hit.get("event_at") or "").strip() for hit in hits if str(hit.get("event_at") or "").strip()}
        if len(event_dates) > 1:
            return "Conflicting temporal evidence about the exact event date."
        if not event_dates:
            valid_from_values = {str(hit.get("valid_from") or "").strip() for hit in hits if str(hit.get("valid_from") or "").strip()}
            if len(valid_from_values) > 1:
                return "Conflicting temporal evidence about when that state began."
        return ""

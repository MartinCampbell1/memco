from __future__ import annotations

import hashlib
import json
import re
import time

from memco.llm_usage import LLMUsageEvent, LLMUsageTracker, estimate_token_count
from memco.models.relationships import canonical_relation_type
from memco.repositories.retrieval_log_repository import RetrievalLogRepository
from memco.models.retrieval import DetailPolicy, RefusalCategory, RetrievalHit, RetrievalPlan, RetrievalRequest, RetrievalResult
from memco.repositories.fact_repository import FactRepository
from memco.repositories.retrieval_repository import RetrievalRepository
from memco.services.planner_service import PlannerService


EXPLICIT_SUBJECT_PATTERNS = (
    re.compile(
        r"^\s*(?:(?i:where|what|when|why|how))\s+(?:(?i:does|did|is|was|can|could|will|would))\s+([A-Z][A-Za-z0-9&.\-]*(?:\s+(?:[A-Z][A-Za-z0-9&.\-]*|\d+))*)\b",
    ),
    re.compile(
        r"^\s*(?:(?i:does|did|is|was|can|could|will|would))\s+([A-Z][A-Za-z0-9&.\-]*(?:\s+(?:[A-Z][A-Za-z0-9&.\-]*|\d+))*)\b",
    ),
    re.compile(r"^\s*(?:(?i:who))\s+(?:(?i:is))\s+([A-Z][A-Za-z0-9&.\-]*(?:\s+(?:[A-Z][A-Za-z0-9&.\-]*|\d+))*)\b"),
    re.compile(r"^\s*(?:(?i:tell me about|describe|show me))\s+([A-Z][A-Za-z0-9&.\-]*(?:\s+(?:[A-Z][A-Za-z0-9&.\-]*|\d+))*)\b"),
)


class RetrievalService:
    NON_FACTUAL_DOMAINS = {"style", "psychometrics"}
    RESIDENCE_FIELDS = ("city", "place")
    ORG_FIELDS = ("org", "company", "employer")
    PREFERENCE_FIELDS = ("value",)
    EVENT_FIELDS = ("event",)
    YES_NO_PREFIXES = (
        "do",
        "does",
        "did",
        "is",
        "are",
        "was",
        "were",
        "can",
        "could",
        "will",
        "would",
        "has",
        "have",
        "had",
        "should",
    )

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
        refusal_category: RefusalCategory = "unsupported_no_evidence",
        target_person: dict | None = None,
    ) -> RetrievalResult:
        unsupported_claims = [reason] if reason else []
        return RetrievalResult(
            query=query,
            answerable=False,
            unsupported_premise_detected=True,
            support_level="unsupported",
            refusal_category=refusal_category,
            must_not_use_as_fact=True,
            detail_policy=detail_policy,
            unsupported_claims=unsupported_claims,
            safe_known_facts=[],
            target_person=target_person or {},
            hits=[],
            planner=planner,
        )

    def _target_person_payload(self, person: dict | None) -> dict:
        if person is None:
            return {}
        return {
            "id": int(person["id"]),
            "slug": str(person.get("slug") or ""),
            "display_name": str(person.get("display_name") or ""),
        }

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
                    answerable=False,
                    unsupported_premise_detected=True,
                    support_level="unsupported",
                    refusal_category="unsupported_no_evidence",
                    must_not_use_as_fact=True,
                    detail_policy=payload.detail_policy,
                    unsupported_claims=["Unknown person."],
                    safe_known_facts=[],
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
                refusal_category="subject_mismatch",
                target_person=self._target_person_payload(person),
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
                    target_person=self._target_person_payload(person),
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
        hits = self._filter_relationship_hits_for_requested_relation(planner=planner, hits=hits)
        hits = self._dedupe_relationship_mirror_hits(hits=hits)
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
        answerable = self._answerable_from_support(
            query=payload.query,
            support_level=support_level,
            unsupported_checks=unsupported_checks,
        )
        refusal_category = self._refusal_category(
            query=payload.query,
            planner=planner,
            support_level=support_level,
            unsupported_checks=unsupported_checks,
            unsupported_claims=unsupported_claims,
        )
        safe_known_facts = self._safe_known_facts(hits=hits)
        result = RetrievalResult(
            query=payload.query,
            answerable=answerable,
            unsupported_premise_detected=unsupported_flag,
            support_level=support_level,
            refusal_category=refusal_category,
            must_not_use_as_fact=not answerable,
            detail_policy=payload.detail_policy,
            unsupported_claims=unsupported_claims,
            safe_known_facts=safe_known_facts,
            target_person=self._target_person_payload(person),
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

    def _is_yes_no_query(self, query: str) -> bool:
        first = query.strip().split(maxsplit=1)[0].lower().strip("¿?!.:,;") if query.strip() else ""
        return first in self.YES_NO_PREFIXES

    def _answerable_from_support(self, *, query: str, support_level: str, unsupported_checks: list) -> bool:
        if support_level == "supported":
            return True
        if support_level == "partial":
            return not unsupported_checks
        return False

    def _refusal_category(
        self,
        *,
        query: str,
        planner: RetrievalPlan,
        support_level: str,
        unsupported_checks: list,
        unsupported_claims: list[str],
    ) -> RefusalCategory:
        if support_level == "supported":
            return ""
        if any(claim == "Query subject does not match requested person." for claim in unsupported_claims):
            return "subject_mismatch"
        if support_level == "contradicted":
            return "contradicted_by_memory"
        if support_level == "partial":
            if unsupported_checks:
                return "unsupported_no_evidence"
            return ""
        if support_level == "ambiguous":
            if any(check.claim_type in {"relation", "relation_target"} for check in unsupported_checks) or any(
                domain_query.domain == "social_circle" for domain_query in planner.domain_queries
            ):
                return "ambiguous_relationship"
            return "insufficient_evidence"
        return "unsupported_no_evidence"

    def _safe_known_facts(self, *, hits: list[dict]) -> list[str]:
        facts: list[str] = []
        seen: set[str] = set()
        for hit in hits:
            if hit.get("domain") in self.NON_FACTUAL_DOMAINS:
                continue
            summary = str(hit.get("summary") or "").strip()
            if not summary or summary in seen:
                continue
            seen.add(summary)
            facts.append(summary)
        return facts

    def _requested_relationship_relations(self, *, planner: RetrievalPlan) -> set[str]:
        if not any(domain_query.domain == "social_circle" for domain_query in planner.domain_queries):
            return set()
        return {
            canonical_relation_type(check.value)
            for check in planner.claim_checks
            if check.claim_type == "relation"
        }

    def _requested_relationship_targets(self, *, planner: RetrievalPlan) -> set[str]:
        if not any(domain_query.domain == "social_circle" for domain_query in planner.domain_queries):
            return set()
        return {
            self._normalize_person_label(check.value)
            for check in planner.claim_checks
            if check.claim_type in {"relation_target", "name"}
        }

    def _relationship_hit_relation(self, hit: dict) -> str:
        if hit.get("domain") == "biography" and hit.get("category") != "family":
            return ""
        if hit.get("domain") not in {"social_circle", "biography"}:
            return ""
        payload = hit.get("payload", {})
        relation = payload.get("relation") or hit.get("subcategory") or hit.get("category")
        return canonical_relation_type(str(relation or ""))

    def _filter_relationship_hits_for_requested_relation(self, *, planner: RetrievalPlan, hits: list[dict]) -> list[dict]:
        requested_relations = self._requested_relationship_relations(planner=planner)
        requested_targets = self._requested_relationship_targets(planner=planner)
        if not requested_relations:
            return hits
        filtered: list[dict] = []
        for hit in hits:
            relation = self._relationship_hit_relation(hit)
            if not relation:
                filtered.append(hit)
                continue
            if relation in requested_relations:
                filtered.append(hit)
                continue
            payload = hit.get("payload", {})
            target_label = self._normalize_person_label(str(payload.get("target_label") or payload.get("name") or ""))
            if target_label and target_label in requested_targets:
                filtered.append(hit)
        return filtered

    def _relationship_hit_target(self, hit: dict) -> str:
        payload = hit.get("payload", {})
        return self._normalize_person_label(str(payload.get("target_label") or payload.get("name") or ""))

    def _is_derived_relationship_mirror(self, hit: dict) -> bool:
        payload = hit.get("payload", {})
        return hit.get("source_kind") == "derived_mirror" or bool(payload.get("mirrored_from_fact_id"))

    def _dedupe_relationship_mirror_hits(self, *, hits: list[dict]) -> list[dict]:
        deduped: list[dict] = []
        key_to_index: dict[tuple[str, str], int] = {}
        for hit in hits:
            relation = self._relationship_hit_relation(hit)
            target = self._relationship_hit_target(hit)
            if not relation or not target:
                deduped.append(hit)
                continue
            key = (relation, target)
            existing_index = key_to_index.get(key)
            if existing_index is None:
                key_to_index[key] = len(deduped)
                deduped.append(hit)
                continue
            existing = deduped[existing_index]
            if self._is_derived_relationship_mirror(existing) and not self._is_derived_relationship_mirror(hit):
                deduped[existing_index] = hit
        return deduped

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
            if check.claim_type == "relation":
                relation = canonical_relation_type(check.value)
                if relation and relation in self._relationship_relations(hits=hits):
                    continue
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

    def _normalized_work_orgs(self, *, hits: list[dict]) -> set[str]:
        values: set[str] = set()
        for hit in hits:
            if hit.get("domain") != "work" or hit.get("category") not in {"employment", "org"}:
                continue
            payload = hit.get("payload", {})
            for field in self.ORG_FIELDS:
                value = payload.get(field)
                if value is None:
                    continue
                values.add(self._normalize_person_label(str(value)))
        return values

    def _relationship_targets(self, *, hits: list[dict]) -> set[str]:
        targets: set[str] = set()
        for hit in hits:
            if hit.get("domain") not in {"social_circle", "biography"}:
                continue
            if hit.get("domain") == "biography" and hit.get("category") != "family":
                continue
            payload = hit.get("payload", {})
            for field in ("target_label", "name"):
                value = payload.get(field)
                if value:
                    targets.add(self._normalize_person_label(str(value)))
        return targets

    def _relationship_relations(self, *, hits: list[dict]) -> set[str]:
        relations: set[str] = set()
        for hit in hits:
            if hit.get("domain") not in {"social_circle", "biography"}:
                continue
            if hit.get("domain") == "biography" and hit.get("category") != "family":
                continue
            payload = hit.get("payload", {})
            relation = payload.get("relation") or hit.get("subcategory") or hit.get("category")
            if relation:
                relations.add(canonical_relation_type(str(relation)))
        return relations

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
        if not hits or not unsupported_checks:
            return False
        if any(domain_query.domain == "social_circle" for domain_query in planner.domain_queries):
            target_checks = {
                self._normalize_person_label(check.value)
                for check in planner.claim_checks
                if check.claim_type in {"relation_target", "name"}
            }
            relation_checks = {
                canonical_relation_type(check.value)
                for check in unsupported_checks
                if check.claim_type == "relation"
            }
            supported_targets = self._relationship_targets(hits=hits)
            supported_relations = self._relationship_relations(hits=hits)
            if (
                target_checks
                and supported_targets
                and supported_relations
                and any(target not in supported_targets for target in target_checks)
            ):
                return True
            if relation_checks and supported_relations and all(relation not in supported_relations for relation in relation_checks):
                return True
            if target_checks and relation_checks:
                for hit in hits:
                    payload = hit.get("payload", {})
                    target_label = self._normalize_person_label(str(payload.get("target_label") or payload.get("name") or ""))
                    relation = canonical_relation_type(str(payload.get("relation") or hit.get("category") or ""))
                    if target_label in target_checks and relation and relation not in relation_checks:
                        return True
        if len(planner.domain_queries) != 1:
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
            supported_orgs = self._normalized_work_orgs(hits=hits)
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

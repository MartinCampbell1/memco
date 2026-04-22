from __future__ import annotations

from memco.models.retrieval import DetailPolicy


class AnswerService:
    NON_FACTUAL_DOMAINS = {"style", "psychometrics"}

    def _temporal_value(self, hit) -> tuple[str, str]:
        event_at = str(getattr(hit, "event_at", "") or "").strip()
        if event_at:
            return "event_at", event_at
        valid_from = str(getattr(hit, "valid_from", "") or "").strip()
        if valid_from:
            return "valid_from", valid_from
        observed_at = str(getattr(hit, "observed_at", "") or "").strip()
        if observed_at:
            return "observed_at", observed_at
        return "unknown", ""

    def _answer_ids(self, retrieval_result) -> tuple[list[int], list[int]]:
        fact_ids: list[int] = []
        evidence_ids: list[int] = []
        for hit in retrieval_result.hits:
            fact_ids.append(int(hit.fact_id))
            for evidence in hit.evidence:
                evidence_id = evidence.get("evidence_id")
                if evidence_id is None:
                    continue
                evidence_ids.append(int(evidence_id))
        return fact_ids, evidence_ids

    def _present_hit(self, hit, *, detail_policy: DetailPolicy) -> dict:
        if detail_policy == "core_only":
            return {
                "fact_id": int(hit.fact_id),
                "domain": hit.domain,
                "category": hit.category,
                "summary": hit.summary,
            }
        return hit.model_dump(mode="json")

    def _payload(self, *, answer: str, refused: bool, retrieval_result, detail_policy: DetailPolicy) -> dict:
        fact_ids, evidence_ids = self._answer_ids(retrieval_result)
        return {
            "answer": answer,
            "refused": refused,
            "detail_policy": detail_policy,
            "hits": [self._present_hit(hit, detail_policy=detail_policy) for hit in retrieval_result.hits],
            "fact_ids": fact_ids,
            "evidence_ids": evidence_ids,
        }

    def _factual_hits(self, retrieval_result):
        return [hit for hit in retrieval_result.hits if getattr(hit, "domain", "") not in self.NON_FACTUAL_DOMAINS]

    def _temporal_conflict_answer(self, factual_hits) -> str:
        event_dates = {str(getattr(hit, "event_at", "") or "").strip() for hit in factual_hits if str(getattr(hit, "event_at", "") or "").strip()}
        if len(event_dates) > 1:
            return "I have conflicting memory evidence about the exact event date."
        valid_from_values = {str(getattr(hit, "valid_from", "") or "").strip() for hit in factual_hits if str(getattr(hit, "valid_from", "") or "").strip()}
        if not event_dates and len(valid_from_values) > 1:
            return "I have conflicting memory evidence about when that state began."
        return ""

    def _select_temporal_hit(self, factual_hits):
        for field in ("event_at", "valid_from", "observed_at"):
            hits = [hit for hit in factual_hits if str(getattr(hit, field, "") or "").strip()]
            if hits:
                return hits[0]
        return factual_hits[0] if factual_hits else None

    def _format_when_answer(self, hit) -> str:
        source, value = self._temporal_value(hit)
        if source == "event_at":
            return f"{hit.summary} The event date is {value}."
        if source == "valid_from":
            return f"{hit.summary} This has been true since {value}."
        if source == "observed_at":
            return f"{hit.summary} The exact event date is unknown; I only know it was recorded on {value}."
        return f"{hit.summary} The exact date is unknown."

    def build_answer(self, *, query: str, retrieval_result, detail_policy: DetailPolicy | None = None) -> dict:
        policy = detail_policy or getattr(retrieval_result, "detail_policy", "balanced")
        factual_hits = self._factual_hits(retrieval_result)
        is_when_query = query.strip().lower().startswith("when") or query.strip().lower().startswith("когда")
        if retrieval_result.hits and not factual_hits:
            sanitized = retrieval_result.model_copy(update={"hits": []})
            return self._payload(
                answer="I don't have confirmed memory evidence for that.",
                refused=True,
                retrieval_result=sanitized,
                detail_policy=policy,
            )
        if is_when_query and factual_hits:
            conflict_answer = self._temporal_conflict_answer(factual_hits)
            if conflict_answer:
                return self._payload(
                    answer=conflict_answer,
                    refused=True,
                    retrieval_result=retrieval_result,
                    detail_policy=policy,
                )
        if retrieval_result.support_level in {"unsupported", "ambiguous"}:
            return self._payload(
                answer="I don't have confirmed memory evidence for that.",
                refused=True,
                retrieval_result=retrieval_result,
                detail_policy=policy,
            )
        if retrieval_result.support_level == "contradicted":
            supported = " ".join(hit.summary for hit in factual_hits).strip()
            answer = "Confirmed memory conflicts with that claim."
            if supported:
                answer = f"{answer} {supported}".strip()
            return self._payload(answer=answer, refused=True, retrieval_result=retrieval_result, detail_policy=policy)
        if retrieval_result.support_level == "partial":
            supported = " ".join(hit.summary for hit in factual_hits).strip()
            unsupported = " ".join(retrieval_result.unsupported_claims).strip()
            if supported and unsupported:
                answer = f"{supported} However, {unsupported}"
            else:
                answer = supported or unsupported or "I only have partial memory evidence for that."
            return self._payload(answer=answer, refused=False, retrieval_result=retrieval_result, detail_policy=policy)
        if is_when_query and factual_hits:
            first_hit = self._select_temporal_hit(factual_hits)
            if first_hit is not None:
                return self._payload(
                    answer=self._format_when_answer(first_hit),
                    refused=False,
                    retrieval_result=retrieval_result,
                    detail_policy=policy,
                )
        return self._payload(
            answer=" ".join(hit.summary for hit in factual_hits),
            refused=False,
            retrieval_result=retrieval_result,
            detail_policy=policy,
        )

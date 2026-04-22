from __future__ import annotations

from memco.models.retrieval import DetailPolicy


class AnswerService:
    def _temporal_value(self, hit) -> str:
        return str(getattr(hit, "event_at", "") or getattr(hit, "valid_from", "") or getattr(hit, "observed_at", "")).strip()

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

    def build_answer(self, *, query: str, retrieval_result, detail_policy: DetailPolicy | None = None) -> dict:
        policy = detail_policy or getattr(retrieval_result, "detail_policy", "balanced")
        if retrieval_result.support_level in {"unsupported", "ambiguous"}:
            return self._payload(
                answer="I don't have confirmed memory evidence for that.",
                refused=True,
                retrieval_result=retrieval_result,
                detail_policy=policy,
            )
        if retrieval_result.support_level == "contradicted":
            supported = " ".join(hit.summary for hit in retrieval_result.hits).strip()
            answer = "Confirmed memory conflicts with that claim."
            if supported:
                answer = f"{answer} {supported}".strip()
            return self._payload(answer=answer, refused=True, retrieval_result=retrieval_result, detail_policy=policy)
        if retrieval_result.support_level == "partial":
            supported = " ".join(hit.summary for hit in retrieval_result.hits).strip()
            unsupported = " ".join(retrieval_result.unsupported_claims).strip()
            if supported and unsupported:
                answer = f"{supported} However, {unsupported}"
            else:
                answer = supported or unsupported or "I only have partial memory evidence for that."
            return self._payload(answer=answer, refused=False, retrieval_result=retrieval_result, detail_policy=policy)
        if query.strip().lower().startswith("when") and retrieval_result.hits:
            first_hit = retrieval_result.hits[0]
            temporal_value = self._temporal_value(first_hit)
            if temporal_value:
                return self._payload(
                    answer=f"{first_hit.summary} It happened in {temporal_value}.",
                    refused=False,
                    retrieval_result=retrieval_result,
                    detail_policy=policy,
                )
        return self._payload(
            answer=" ".join(hit.summary for hit in retrieval_result.hits),
            refused=False,
            retrieval_result=retrieval_result,
            detail_policy=policy,
        )

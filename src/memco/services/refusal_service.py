from __future__ import annotations


class RefusalService:
    def build_answer(self, *, query: str, retrieval_result) -> dict:
        if retrieval_result.support_level == "none":
            return {
                "answer": "I don't have confirmed memory evidence for that.",
                "refused": True,
                "hits": [],
            }
        if retrieval_result.support_level == "partial":
            supported = " ".join(hit.summary for hit in retrieval_result.hits).strip()
            unsupported = " ".join(retrieval_result.unsupported_claims).strip()
            if supported and unsupported:
                answer = f"{supported} However, {unsupported}"
            else:
                answer = supported or unsupported or "I only have partial memory evidence for that."
            return {
                "answer": answer,
                "refused": False,
                "hits": [hit.model_dump(mode="json") for hit in retrieval_result.hits],
            }
        return {
            "answer": " ".join(hit.summary for hit in retrieval_result.hits),
            "refused": False,
            "hits": [hit.model_dump(mode="json") for hit in retrieval_result.hits],
        }

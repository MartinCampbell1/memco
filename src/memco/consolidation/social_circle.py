from __future__ import annotations

from memco.consolidation.base import ConsolidationPolicy


class SocialCircleConsolidationPolicy(ConsolidationPolicy):
    domain = "social_circle"

    def publish_block_reason(self, *, category: str, payload: dict) -> str | None:
        if payload.get("target_person_id") is None:
            return "Cannot publish social_circle candidate with unresolved hard conflict"
        return None

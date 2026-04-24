from __future__ import annotations

from memco.consolidation.base import ConsolidationPolicy


class SocialCircleConsolidationPolicy(ConsolidationPolicy):
    domain = "social_circle"

    def semantic_duplicate_key(self, *, category: str, payload: dict) -> str:
        if category == "relationship_event":
            return f"relationship_event:{self._first_value(payload, 'target_person_id', 'target_label', 'related_person_name')}:{self._first_value(payload, 'event')}"
        relation = self._first_value(payload, "relation") or category
        target = self._first_value(payload, "target_person_id", "target_label", "related_person_name")
        return f"{relation}:{target}"

    def publish_block_reason(self, *, category: str, payload: dict) -> str | None:
        if payload.get("target_person_id") is None:
            return "Cannot publish social_circle candidate with unresolved hard conflict"
        return None

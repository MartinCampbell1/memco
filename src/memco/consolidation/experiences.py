from __future__ import annotations

from memco.consolidation.base import ConsolidationPolicy


class ExperiencesConsolidationPolicy(ConsolidationPolicy):
    domain = "experiences"

    def semantic_duplicate_key(self, *, category: str, payload: dict) -> str:
        if category == "event":
            return f"event:{self._first_value(payload, 'event', 'summary')}:{self._first_value(payload, 'event_at', 'date_range')}:{self._first_value(payload, 'location')}"
        return super().semantic_duplicate_key(category=category, payload=payload)

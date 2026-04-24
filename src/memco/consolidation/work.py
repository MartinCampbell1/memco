from __future__ import annotations

from memco.consolidation.base import ConsolidationDecision, ConsolidationPolicy


class WorkConsolidationPolicy(ConsolidationPolicy):
    domain = "work"
    current_state_categories = frozenset({"employment", "role", "org"})

    def semantic_duplicate_key(self, *, category: str, payload: dict) -> str:
        if category == "employment":
            return f"employment:{self._first_value(payload, 'org', 'company', 'client')}:{self._first_value(payload, 'title', 'role')}"
        if category == "role":
            return f"role:{self._first_value(payload, 'role', 'title')}"
        if category == "org":
            return f"org:{self._first_value(payload, 'org', 'company', 'client')}"
        if category == "project":
            return f"project:{self._first_value(payload, 'project', 'name')}:{self._first_value(payload, 'org', 'client')}"
        if category == "skill":
            return f"skill:{self._first_value(payload, 'skill', 'value')}"
        if category == "tool":
            return f"tool:{self._first_value(payload, 'tool', 'value')}"
        return super().semantic_duplicate_key(category=category, payload=payload)

    def resolve(
        self,
        *,
        category: str,
        canonical_key: str,
        payload: dict,
        observed_at: str,
        existing_fact: dict | None,
    ) -> ConsolidationDecision:
        decision = super().resolve(
            category=category,
            canonical_key=canonical_key,
            payload=payload,
            observed_at=observed_at,
            existing_fact=existing_fact,
        )
        if decision.action == "supersede_existing":
            return ConsolidationDecision(
                action="supersede_existing",
                conflict_kind="value_conflict",
                reason=f"{category} update supersedes the previous current work fact",
            )
        return decision

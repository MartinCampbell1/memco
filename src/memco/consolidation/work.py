from __future__ import annotations

from memco.consolidation.base import ConsolidationDecision, ConsolidationPolicy


class WorkConsolidationPolicy(ConsolidationPolicy):
    domain = "work"
    current_state_categories = frozenset({"employment", "role", "org"})

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


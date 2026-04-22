from __future__ import annotations

from memco.consolidation.base import ConsolidationDecision, ConsolidationPolicy


class BiographyConsolidationPolicy(ConsolidationPolicy):
    domain = "biography"
    current_state_categories = frozenset({"residence"})

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
                reason="residence update supersedes the previous current residence",
            )
        return decision


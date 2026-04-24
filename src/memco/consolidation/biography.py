from __future__ import annotations

from memco.consolidation.base import ConsolidationDecision, ConsolidationPolicy


class BiographyConsolidationPolicy(ConsolidationPolicy):
    domain = "biography"
    current_state_categories = frozenset({"residence"})

    def semantic_duplicate_key(self, *, category: str, payload: dict) -> str:
        if category == "residence":
            return f"residence:{self._first_value(payload, 'city', 'place')}"
        if category == "origin":
            return f"origin:{self._first_value(payload, 'place', 'city')}"
        if category == "family":
            return f"family:{self._first_value(payload, 'relation')}:{self._first_value(payload, 'target_person_id', 'target_label', 'name')}"
        if category == "languages":
            return f"languages:{self._first_value(payload, 'languages', 'language')}"
        if category == "pets":
            return f"pets:{self._first_value(payload, 'pet_type')}:{self._first_value(payload, 'pet_name')}"
        if category == "identity":
            return f"identity:{self._first_value(payload, 'name')}"
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
                reason="residence update supersedes the previous current residence",
            )
        return decision

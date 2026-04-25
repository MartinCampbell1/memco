from __future__ import annotations

from memco.consolidation.base import ConsolidationDecision, ConsolidationPolicy


class PreferencesConsolidationPolicy(ConsolidationPolicy):
    domain = "preferences"
    current_state_categories = frozenset({"preference"})

    def semantic_duplicate_key(self, *, category: str, payload: dict) -> str:
        if category == "preference":
            return ":".join(
                [
                    "preference",
                    self._first_value(payload, "preference_domain", "preference_category"),
                    self._first_value(payload, "value"),
                    self._first_value(payload, "polarity"),
                ]
            )
        return super().semantic_duplicate_key(category=category, payload=payload)

    def current_state_key(self, *, category: str, canonical_key: str, payload: dict) -> str:
        if category == "preference":
            return ":".join(
                [
                    "preference",
                    self._first_value(payload, "preference_domain", "preference_category"),
                    self._first_value(payload, "value"),
                ]
            )
        return super().current_state_key(category=category, canonical_key=canonical_key, payload=payload)

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
        if decision.action != "supersede_existing" or existing_fact is None:
            return decision
        existing_payload = existing_fact.get("payload") or {}
        if existing_payload.get("polarity") != payload.get("polarity"):
            return ConsolidationDecision(
                action="supersede_existing",
                conflict_kind="polarity_conflict",
                reason="preference polarity changed and supersedes the previous current preference",
            )
        return ConsolidationDecision(
            action="supersede_existing",
            conflict_kind="value_conflict",
            reason="preference update supersedes the previous current preference",
        )

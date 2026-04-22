from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ConsolidationDecision:
    action: str
    conflict_kind: str = ""
    reason: str = ""


class ConsolidationPolicy:
    domain = "default"
    current_state_categories: frozenset[str] = frozenset()

    def is_current_state(self, category: str) -> bool:
        return category in self.current_state_categories

    def publish_block_reason(self, *, category: str, payload: dict) -> str | None:
        return None

    def _is_older_than_current(self, *, existing_fact: dict, observed_at: str) -> bool:
        existing_observed_at = str(existing_fact.get("observed_at") or "")
        return bool(existing_observed_at and observed_at and observed_at < existing_observed_at)

    def resolve(
        self,
        *,
        category: str,
        canonical_key: str,
        payload: dict,
        observed_at: str,
        existing_fact: dict | None,
    ) -> ConsolidationDecision:
        if existing_fact is None:
            return ConsolidationDecision(action="insert_active")
        if not self.is_current_state(category):
            return ConsolidationDecision(action="insert_active")
        if self._is_older_than_current(existing_fact=existing_fact, observed_at=observed_at):
            return ConsolidationDecision(
                action="insert_historical",
                conflict_kind="temporal_conflict",
                reason="older historical evidence arrived after the current fact",
            )
        return ConsolidationDecision(
            action="supersede_existing",
            conflict_kind="value_conflict",
            reason="new current-state fact supersedes the previous active fact",
        )


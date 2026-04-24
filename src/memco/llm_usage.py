from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from memco.utils import isoformat_z


@dataclass(frozen=True)
class LLMUsageEvent:
    provider: str
    model: str
    operation: str
    input_tokens: int
    output_tokens: int
    estimated_cost_usd: float | None
    deterministic: bool
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=isoformat_z)


def estimate_token_count(*texts: str) -> int:
    total = 0
    for text in texts:
        cleaned = (text or "").strip()
        if not cleaned:
            continue
        total += max(1, math.ceil(len(cleaned) / 4))
    return total


class LLMUsageTracker:
    def __init__(self) -> None:
        self._events: list[LLMUsageEvent] = []

    @property
    def events(self) -> list[LLMUsageEvent]:
        return list(self._events)

    def reset(self) -> None:
        self._events.clear()

    def record(self, event: LLMUsageEvent) -> None:
        self._events.append(event)

    def summary(self, *, start_index: int = 0) -> dict:
        events = self._events[start_index:]
        deterministic = [event for event in events if event.deterministic]
        llm = [event for event in events if not event.deterministic]
        return {
            "implemented": True,
            "status": "tracked",
            "events_logged": len(events),
            "llm_usage": self._aggregate(llm),
            "deterministic_usage": self._aggregate(deterministic),
            "production_accounting": self._production_accounting(events),
        }

    def _aggregate(self, events: list[LLMUsageEvent]) -> dict:
        cost_values = [event.estimated_cost_usd for event in events if event.estimated_cost_usd is not None]
        unknown_cost_event_count = sum(1 for event in events if event.estimated_cost_usd is None)
        if not events:
            estimated_cost_usd: float | None = 0.0
            cost_status = "not_applicable"
        elif unknown_cost_event_count and not cost_values:
            estimated_cost_usd = None
            cost_status = "unknown"
        elif unknown_cost_event_count:
            estimated_cost_usd = round(sum(cost_values), 6)
            cost_status = "partial"
        else:
            estimated_cost_usd = round(sum(cost_values), 6)
            cost_status = "known"
        return {
            "operation_count": len(events),
            "input_tokens": sum(event.input_tokens for event in events),
            "output_tokens": sum(event.output_tokens for event in events),
            "estimated_cost_usd": estimated_cost_usd,
            "cost_status": cost_status,
            "known_cost_event_count": len(cost_values),
            "unknown_cost_event_count": unknown_cost_event_count,
            "providers": sorted({event.provider for event in events}),
        }

    def _production_accounting(self, events: list[LLMUsageEvent]) -> dict:
        extraction_events = [event for event in events if event.metadata.get("stage") == "extraction"]
        extraction_usage = self._aggregate(extraction_events)
        extraction_cost = extraction_usage["estimated_cost_usd"]
        candidate_count = sum(int(event.metadata.get("candidate_count") or 0) for event in extraction_events)
        by_stage = self._group_by_metadata(events, "stage")
        for stage in ("extraction", "planner", "retrieval", "answer"):
            by_stage.setdefault(stage, self._aggregate([]))
        return {
            "by_stage": by_stage,
            "by_source_id": self._group_by_metadata(events, "source_id", "source_ids"),
            "by_person_id": self._group_by_metadata(events, "person_id", "person_ids"),
            "by_domain": self._group_by_metadata(events, "domain", "domains"),
            "retrieved_context_tokens": sum(int(event.metadata.get("retrieved_context_tokens") or 0) for event in events),
            "amortized_extraction": {
                "candidate_count": candidate_count,
                "estimated_cost_usd": extraction_cost,
                "estimated_cost_usd_per_candidate": None
                if extraction_cost is None
                else (round(extraction_cost / candidate_count, 6) if candidate_count else 0.0),
                "cost_status": extraction_usage["cost_status"],
                "known_cost_event_count": extraction_usage["known_cost_event_count"],
                "unknown_cost_event_count": extraction_usage["unknown_cost_event_count"],
            },
        }

    def _group_by_metadata(self, events: list[LLMUsageEvent], key: str, list_key: str | None = None) -> dict:
        grouped: dict[str, list[LLMUsageEvent]] = {}
        for event in events:
            values = self._metadata_values(event.metadata, key, list_key)
            for value in values:
                grouped.setdefault(value, []).append(event)
        return {
            value: self._aggregate(grouped[value])
            for value in sorted(grouped)
        }

    def _metadata_values(self, metadata: dict[str, Any], key: str, list_key: str | None) -> list[str]:
        raw_values: list[Any] = []
        if list_key and list_key in metadata:
            value = metadata.get(list_key)
            if isinstance(value, list):
                raw_values.extend(value)
            elif value not in {None, ""}:
                raw_values.append(value)
        if key in metadata and metadata.get(key) not in {None, ""}:
            raw_values.append(metadata.get(key))
        values = sorted({str(value) for value in raw_values if value not in {None, ""}})
        return values


class LLMUsageFileLogger:
    def __init__(self, path: Path) -> None:
        self.path = path

    def record(self, event: LLMUsageEvent) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(asdict(event), ensure_ascii=False) + "\n")

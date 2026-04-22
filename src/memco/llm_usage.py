from __future__ import annotations

import json
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

    def summary(self) -> dict:
        deterministic = [event for event in self._events if event.deterministic]
        llm = [event for event in self._events if not event.deterministic]
        return {
            "implemented": True,
            "status": "tracked",
            "events_logged": len(self._events),
            "llm_usage": self._aggregate(llm),
            "deterministic_usage": self._aggregate(deterministic),
        }

    def _aggregate(self, events: list[LLMUsageEvent]) -> dict:
        cost_values = [event.estimated_cost_usd for event in events if event.estimated_cost_usd is not None]
        return {
            "operation_count": len(events),
            "input_tokens": sum(event.input_tokens for event in events),
            "output_tokens": sum(event.output_tokens for event in events),
            "estimated_cost_usd": round(sum(cost_values), 6) if cost_values else (0.0 if events else 0.0),
            "providers": sorted({event.provider for event in events}),
        }


class LLMUsageFileLogger:
    def __init__(self, path: Path) -> None:
        self.path = path

    def record(self, event: LLMUsageEvent) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(asdict(event), ensure_ascii=False) + "\n")

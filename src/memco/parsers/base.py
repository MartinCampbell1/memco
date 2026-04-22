from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol


@dataclass(frozen=True)
class ParsedDocument:
    text: str
    parser_name: str
    confidence: float = 1.0
    metadata: dict[str, object] = field(default_factory=dict)


class Parser(Protocol):
    def parse(self, path: Path) -> ParsedDocument: ...

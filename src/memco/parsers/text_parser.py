from __future__ import annotations

from pathlib import Path

from memco.parsers.base import ParsedDocument


class TextParser:
    def parse(self, path: Path) -> ParsedDocument:
        return ParsedDocument(
            text=path.read_text(encoding="utf-8", errors="ignore"),
            parser_name="text",
            confidence=1.0,
        )

from __future__ import annotations

import json
from pathlib import Path

from memco.parsers.base import ParsedDocument


class JsonParser:
    def parse(self, path: Path) -> ParsedDocument:
        data = json.loads(path.read_text(encoding="utf-8", errors="ignore"))
        return ParsedDocument(
            text=json.dumps(data, ensure_ascii=False, indent=2),
            parser_name="json",
            confidence=1.0,
        )

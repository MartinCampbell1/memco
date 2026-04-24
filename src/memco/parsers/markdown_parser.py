from __future__ import annotations

import json
from pathlib import Path

import yaml

from memco.parsers.base import ParsedDocument


class MarkdownParser:
    def parse(self, path: Path) -> ParsedDocument:
        raw = path.read_text(encoding="utf-8", errors="ignore")
        frontmatter_raw, body = self._split_frontmatter(raw)
        metadata: dict[str, object] = {}
        if frontmatter_raw:
            parsed = yaml.safe_load(frontmatter_raw) or {}
            if isinstance(parsed, dict):
                frontmatter = json.loads(json.dumps(parsed, default=str))
                metadata["frontmatter"] = frontmatter
                if isinstance(frontmatter.get("title"), str):
                    metadata["title"] = frontmatter["title"]
                if isinstance(frontmatter.get("date"), str):
                    metadata["date"] = frontmatter["date"]

        text = body.strip()
        return ParsedDocument(
            text=text + ("\n" if text else ""),
            parser_name="markdown",
            confidence=1.0,
            metadata=metadata,
        )

    def _split_frontmatter(self, raw: str) -> tuple[str, str]:
        lines = raw.splitlines()
        if not lines or lines[0].strip() != "---":
            return "", raw
        for index, line in enumerate(lines[1:], start=1):
            if line.strip() == "---":
                return "\n".join(lines[1:index]), "\n".join(lines[index + 1 :])
        return "", raw

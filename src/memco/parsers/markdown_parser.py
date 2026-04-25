from __future__ import annotations

import json
from pathlib import Path

import yaml

from memco.parsers.base import ParsedDocument


class MarkdownParser:
    def parse(self, path: Path) -> ParsedDocument:
        raw = path.read_text(encoding="utf-8", errors="ignore")
        frontmatter_raw, body, body_offset = self._split_frontmatter(raw)
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

        leading_trim = len(body) - len(body.lstrip())
        text = body.strip()
        document_segments = self._section_segments(
            path=path,
            text=text,
            base_offset=body_offset + leading_trim,
            journal_date=str(metadata.get("date") or ""),
        )
        if document_segments:
            metadata["document_segments"] = document_segments
        return ParsedDocument(
            text=text + ("\n" if text else ""),
            parser_name="markdown",
            confidence=1.0,
            metadata=metadata,
        )

    def _split_frontmatter(self, raw: str) -> tuple[str, str, int]:
        lines = raw.splitlines(keepends=True)
        if not lines or lines[0].strip() != "---":
            return "", raw, 0
        offset = len(lines[0])
        frontmatter_lines: list[str] = []
        for line in lines[1:]:
            if line.strip() == "---":
                return "".join(frontmatter_lines).strip(), raw[offset + len(line) :], offset + len(line)
            frontmatter_lines.append(line)
            offset += len(line)
        return "", raw, 0

    def _section_segments(self, *, path: Path, text: str, base_offset: int, journal_date: str) -> list[dict[str, object]]:
        if not text.strip():
            return []

        lines = text.splitlines(keepends=True)
        headings: list[tuple[int, str]] = []
        offset = 0
        in_fence = False
        for line in lines:
            stripped = line.strip()
            if stripped.startswith("```") or stripped.startswith("~~~"):
                in_fence = not in_fence
            elif not in_fence and stripped.startswith("#"):
                title = stripped.lstrip("#").strip()
                if title:
                    headings.append((offset, title))
            offset += len(line)

        if not headings:
            return [
                self._segment(
                    path=path,
                    title=path.stem,
                    text=text,
                    start=base_offset,
                    end=base_offset + len(text),
                    index=0,
                    journal_date=journal_date,
                    segment_type="markdown_document",
                )
            ]

        segments: list[dict[str, object]] = []
        if headings[0][0] > 0:
            preamble_text = text[: headings[0][0]].strip()
            if preamble_text:
                preamble_end = len(text[: headings[0][0]].rstrip())
                segments.append(
                    self._segment(
                        path=path,
                        title=path.stem,
                        text=preamble_text,
                        start=base_offset,
                        end=base_offset + preamble_end,
                        index=0,
                        journal_date=journal_date,
                        segment_type="markdown_preamble",
                    )
                )
        for index, (start, title) in enumerate(headings):
            end = headings[index + 1][0] if index + 1 < len(headings) else len(text)
            raw_segment = text[start:end]
            leading_trim = len(raw_segment) - len(raw_segment.lstrip())
            trailing_trimmed = raw_segment.rstrip()
            segment_text = raw_segment.strip()
            if not segment_text:
                continue
            segments.append(
                self._segment(
                    path=path,
                    title=title,
                    text=segment_text,
                    start=base_offset + start + leading_trim,
                    end=base_offset + start + len(trailing_trimmed),
                    index=len(segments),
                    journal_date=journal_date,
                    segment_type="markdown_section",
                )
            )
        return segments

    def _segment(
        self,
        *,
        path: Path,
        title: str,
        text: str,
        start: int,
        end: int,
        index: int,
        journal_date: str,
        segment_type: str,
    ) -> dict[str, object]:
        locator: dict[str, object] = {
            "file": str(path),
            "heading": title,
            "char_start": start,
            "char_end": end,
        }
        if journal_date:
            locator["date"] = journal_date
        return {
            "segment_type": segment_type,
            "segment_index": index,
            "section_title": title,
            "text": text,
            "locator": locator,
        }

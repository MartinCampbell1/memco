from __future__ import annotations

import csv
from pathlib import Path

from memco.parsers.base import ParsedDocument


class DelimitedParser:
    def __init__(self, *, delimiter: str) -> None:
        self.delimiter = delimiter

    def parse(self, path: Path) -> ParsedDocument:
        rows: list[list[str]] = []
        with path.open("r", encoding="utf-8", errors="ignore", newline="") as handle:
            reader = csv.reader(handle, delimiter=self.delimiter)
            for row in reader:
                rows.append([cell.strip() for cell in row])
        if not rows:
            return ParsedDocument(text="", parser_name="delimited", confidence=1.0)
        header = rows[0]
        body = rows[1:]
        lines = [f"# Table Import: {path.name}", "", "## Columns", ", ".join(header), "", "## Rows"]
        for index, row in enumerate(body, start=1):
            lines.append("- row {}: {}".format(index, "; ".join(f"{column}: {value}" for column, value in zip(header, row) if value)))
        return ParsedDocument(
            text="\n".join(lines).strip() + "\n",
            parser_name="delimited",
            confidence=1.0,
        )

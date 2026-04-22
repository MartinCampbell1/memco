from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

from memco.models.source import ImportResult
from memco.repositories.source_repository import SourceRepository
from memco.utils import sha256_file, sha256_text, slugify


def _extract_plain_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="ignore")


def _extract_json(path: Path) -> str:
    data = json.loads(path.read_text(encoding="utf-8", errors="ignore"))
    return json.dumps(data, ensure_ascii=False, indent=2)


def _extract_delimited(path: Path, delimiter: str) -> str:
    rows: list[list[str]] = []
    with path.open("r", encoding="utf-8", errors="ignore", newline="") as handle:
        reader = csv.reader(handle, delimiter=delimiter)
        for row in reader:
            rows.append([cell.strip() for cell in row])
    if not rows:
        return ""
    header = rows[0]
    body = rows[1:]
    lines = [f"# Table Import: {path.name}", "", "## Columns", ", ".join(header), "", "## Rows"]
    for index, row in enumerate(body, start=1):
        lines.append("- row {}: {}".format(index, "; ".join(f"{column}: {value}" for column, value in zip(header, row) if value)))
    return "\n".join(lines).strip() + "\n"


def extract_text(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in {".md", ".txt"}:
        return _extract_plain_text(path)
    if suffix == ".json":
        return _extract_json(path)
    if suffix == ".csv":
        return _extract_delimited(path, ",")
    return _extract_plain_text(path)


def render_normalized_markdown(source_type: str, original_path: Path, parsed_text: str) -> str:
    return (
        f"---\nsource_type: {source_type}\norigin_path: {original_path}\n---\n\n"
        f"# {original_path.stem}\n\n{parsed_text.strip()}\n"
    )


class IngestService:
    def __init__(self, source_repository: SourceRepository | None = None) -> None:
        self.source_repository = source_repository or SourceRepository()

    def import_file(self, settings, conn, *, workspace_slug: str, path: Path, source_type: str) -> ImportResult:
        path = path.expanduser().resolve()
        raw_dir = settings.root / "var" / "raw" / source_type
        raw_dir.mkdir(parents=True, exist_ok=True)
        copied = raw_dir / path.name
        copied.write_bytes(path.read_bytes())
        parsed_text = extract_text(path)
        normalized_path = copied if copied.suffix.lower() == ".md" else copied.with_name(f"{copied.stem}-normalized.md")
        if normalized_path != copied:
            normalized_path.write_text(
                render_normalized_markdown(source_type, copied, parsed_text),
                encoding="utf-8",
            )
        source_id = self.source_repository.record_source(
            conn,
            workspace_slug=workspace_slug,
            source_path=str(copied),
            source_type=source_type,
            origin_uri=str(path),
            title=path.stem,
            sha256=sha256_file(copied),
            parsed_text=parsed_text,
            meta={"normalized_path": str(normalized_path)},
        )
        self.source_repository.replace_chunks(conn, source_id=source_id, parsed_text=parsed_text)
        return ImportResult(
            source_id=source_id,
            source_path=str(copied),
            normalized_path=str(normalized_path),
            source_type=source_type,
            title=path.stem,
        )

    def import_text(self, settings, conn, *, workspace_slug: str, text: str, title: str, source_type: str) -> ImportResult:
        safe_title = title.strip() or "inline-source"
        raw_dir = settings.root / "var" / "raw" / source_type
        raw_dir.mkdir(parents=True, exist_ok=True)
        filename = f"{slugify(safe_title)}-{sha256_text(text)[:8]}.txt"
        copied = raw_dir / filename
        copied.write_text(text, encoding="utf-8")
        parsed_text = text
        normalized_path = copied.with_name(f"{copied.stem}-normalized.md")
        normalized_path.write_text(
            render_normalized_markdown(source_type, copied, parsed_text),
            encoding="utf-8",
        )
        source_id = self.source_repository.record_source(
            conn,
            workspace_slug=workspace_slug,
            source_path=str(copied),
            source_type=source_type,
            origin_uri=f"inline://{slugify(safe_title)}",
            title=safe_title,
            sha256=sha256_file(copied),
            parsed_text=parsed_text,
            meta={"normalized_path": str(normalized_path)},
        )
        self.source_repository.replace_chunks(conn, source_id=source_id, parsed_text=parsed_text)
        return ImportResult(
            source_id=source_id,
            source_path=str(copied),
            normalized_path=str(normalized_path),
            source_type=source_type,
            title=safe_title,
        )

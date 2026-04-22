from __future__ import annotations

from pathlib import Path

from memco.models.source import ImportResult
from memco.parsers.base import ParsedDocument
from memco.parsers.delimited_parser import DelimitedParser
from memco.parsers.email_parser import EmailParser
from memco.parsers.json_parser import JsonParser
from memco.parsers.pdf_parser import PdfParser
from memco.parsers.text_parser import TextParser
from memco.repositories.source_repository import SourceRepository
from memco.utils import sha256_file, sha256_text, slugify


DEFAULT_PARSERS = {
    ".md": TextParser(),
    ".txt": TextParser(),
    ".json": JsonParser(),
    ".csv": DelimitedParser(delimiter=","),
    ".eml": EmailParser(),
    ".mbox": EmailParser(),
    ".pdf": PdfParser(),
}

SOURCE_TYPE_PARSERS = {
    "note": TextParser(),
    "text": TextParser(),
    "markdown": TextParser(),
    "chat": TextParser(),
    "json": JsonParser(),
    "csv": DelimitedParser(delimiter=","),
    "email": EmailParser(),
    "pdf": PdfParser(),
}


def parse_document(path: Path, *, source_type: str | None = None) -> ParsedDocument:
    normalized_type = (source_type or "").strip().lower()
    parser = SOURCE_TYPE_PARSERS.get(normalized_type) or DEFAULT_PARSERS.get(path.suffix.lower(), TextParser())
    return parser.parse(path)


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
        parsed = parse_document(path, source_type=source_type)
        parsed_text = parsed.text
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
            meta={
                "normalized_path": str(normalized_path),
                "parser_name": parsed.parser_name,
                "parser_confidence": parsed.confidence,
                **parsed.metadata,
            },
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
            meta={
                "normalized_path": str(normalized_path),
                "parser_name": "inline",
                "parser_confidence": 1.0,
            },
        )
        self.source_repository.replace_chunks(conn, source_id=source_id, parsed_text=parsed_text)
        return ImportResult(
            source_id=source_id,
            source_path=str(copied),
            normalized_path=str(normalized_path),
            source_type=source_type,
            title=safe_title,
        )

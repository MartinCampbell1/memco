from __future__ import annotations

from pathlib import Path

from memco.models.source import ImportResult
from memco.parsers.base import ParsedDocument
from memco.parsers.delimited_parser import DelimitedParser
from memco.parsers.email_parser import EmailParser
from memco.parsers.html_parser import HtmlParser
from memco.parsers.json_parser import JsonParser
from memco.parsers.markdown_parser import MarkdownParser
from memco.parsers.pdf_parser import PdfParser
from memco.parsers.text_parser import TextParser
from memco.repositories.source_repository import SourceRepository
from memco.utils import sha256_file, sha256_text, slugify


DEFAULT_PARSERS = {
    ".md": MarkdownParser(),
    ".markdown": MarkdownParser(),
    ".txt": TextParser(),
    ".json": JsonParser(),
    ".csv": DelimitedParser(delimiter=","),
    ".eml": EmailParser(),
    ".mbox": EmailParser(),
    ".pdf": PdfParser(),
    ".html": HtmlParser(),
    ".htm": HtmlParser(),
}

SOURCE_TYPE_PARSERS = {
    "note": TextParser(),
    "text": TextParser(),
    "markdown": MarkdownParser(),
    "chat": TextParser(),
    "json": JsonParser(),
    "csv": DelimitedParser(delimiter=","),
    "email": EmailParser(),
    "pdf": PdfParser(),
    "html": HtmlParser(),
}


def _normalize_source_type(source_type: str | None) -> str:
    normalized = (source_type or "").strip().lower()
    if not normalized:
        raise ValueError("source_type is required")
    return normalized


def _supported_source_types(settings) -> set[str]:
    configured = {str(item).strip().lower() for item in getattr(settings.ingest, "source_types", []) if str(item).strip()}
    return configured & set(SOURCE_TYPE_PARSERS)


def validate_source_type(source_type: str | None, *, supported_types: set[str] | None = None) -> str:
    normalized = _normalize_source_type(source_type)
    allowed = supported_types if supported_types is not None else set(SOURCE_TYPE_PARSERS)
    if normalized not in allowed:
        supported = ", ".join(sorted(allowed))
        raise ValueError(f"unsupported source_type '{normalized}'; supported source_types: {supported}")
    return normalized


def parse_document(path: Path, *, source_type: str | None = None) -> ParsedDocument:
    if source_type is not None:
        normalized_type = validate_source_type(source_type)
        parser = SOURCE_TYPE_PARSERS[normalized_type]
    else:
        parser = DEFAULT_PARSERS.get(path.suffix.lower(), TextParser())
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
        source_type = validate_source_type(source_type, supported_types=_supported_source_types(settings))
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
        source_type = validate_source_type(source_type, supported_types=_supported_source_types(settings))
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

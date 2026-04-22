from __future__ import annotations

from pathlib import Path

from memco.parsers.base import ParsedDocument


class PdfParser:
    def parse(self, path: Path) -> ParsedDocument:
        try:
            from pypdf import PdfReader
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError("PDF parsing requires the optional 'parsers' dependencies") from exc

        reader = PdfReader(str(path))
        pages: list[str] = []
        for index, page in enumerate(reader.pages, start=1):
            text = (page.extract_text() or "").strip()
            if not text:
                continue
            pages.append(f"## Page {index}\n{text}")
        return ParsedDocument(
            text="\n\n".join(pages).strip(),
            parser_name="pdf",
            confidence=0.95 if pages else 0.4,
            metadata={"page_count": len(reader.pages)},
        )

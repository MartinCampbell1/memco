from __future__ import annotations

from pathlib import Path

from memco.parsers.base import ParsedDocument


def _normalize_page_text(value: str) -> str:
    lines = [" ".join(line.split()) for line in value.replace("\x00", "").splitlines()]
    return "\n".join(line for line in lines if line)


class PdfParser:
    def parse(self, path: Path) -> ParsedDocument:
        try:
            from pypdf import PdfReader
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError("PDF parsing requires the optional 'parsers' dependencies") from exc

        reader = PdfReader(str(path))
        pages: list[str] = []
        page_metadata: list[dict[str, object]] = []
        empty_page_numbers: list[int] = []
        for index, page in enumerate(reader.pages, start=1):
            text = _normalize_page_text(page.extract_text() or "")
            if not text:
                empty_page_numbers.append(index)
                page_metadata.append({"page_number": index, "extracted_chars": 0, "empty": True})
                continue
            pages.append(f"## Page {index}\n{text}")
            page_metadata.append({"page_number": index, "extracted_chars": len(text), "empty": False})
        if not pages:
            confidence = 0.4
        elif empty_page_numbers:
            confidence = 0.85
        else:
            confidence = 0.95
        return ParsedDocument(
            text="\n\n".join(pages).strip(),
            parser_name="pdf",
            confidence=confidence,
            metadata={
                "page_count": len(reader.pages),
                "extracted_page_count": len(pages),
                "empty_page_numbers": empty_page_numbers,
                "pages": page_metadata,
            },
        )

from __future__ import annotations

from pathlib import Path

from memco.parsers.base import ParsedDocument


def _normalize_page_line(value: str) -> str:
    cleaned = value.replace("\x00", "").strip()
    if not cleaned:
        return ""
    if "  " in cleaned:
        cells = [" ".join(cell.split()) for cell in cleaned.split("  ") if cell.strip()]
        if len(cells) >= 3:
            return " | ".join(cells)
    return " ".join(cleaned.split())


def _normalize_page_text(value: str) -> str:
    lines = [_normalize_page_line(line) for line in value.splitlines()]
    return "\n".join(line for line in lines if line)


def _section_heading_for_page(page_number: int, text: str) -> str:
    for line in text.splitlines():
        candidate = line.strip()
        if len(candidate) < 4:
            continue
        if candidate.startswith("#"):
            return candidate.lstrip("#").strip() or f"Page {page_number}"
        if candidate.isupper() and any(char.isalpha() for char in candidate):
            return candidate.title()
    return f"Page {page_number}"


class PdfParser:
    def __init__(self, *, ocr_enabled: bool = False) -> None:
        self.ocr_enabled = ocr_enabled

    def _ocr_page_text(self, page, page_number: int) -> str:
        return ""

    def parse(self, path: Path) -> ParsedDocument:
        try:
            from pypdf import PdfReader
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError("PDF parsing requires the optional 'parsers' dependencies") from exc

        reader = PdfReader(str(path))
        pages: list[str] = []
        page_metadata: list[dict[str, object]] = []
        page_segments: list[dict[str, object]] = []
        empty_page_numbers: list[int] = []
        ocr_attempted_page_numbers: list[int] = []
        for index, page in enumerate(reader.pages, start=1):
            text = _normalize_page_text(page.extract_text() or "")
            ocr_attempted = False
            if not text and self.ocr_enabled:
                ocr_attempted = True
                ocr_attempted_page_numbers.append(index)
                text = _normalize_page_text(self._ocr_page_text(page, index))
            if not text:
                empty_page_numbers.append(index)
                page_metadata.append(
                    {
                        "page_number": index,
                        "extracted_chars": 0,
                        "empty": True,
                        "ocr_attempted": ocr_attempted,
                        "section_title": f"Page {index}",
                    }
                )
                continue
            section_title = _section_heading_for_page(index, text)
            rendered_page = f"## Page {index}\n\n{text}"
            pages.append(rendered_page)
            locator = {"page_number": index, "page_label": f"Page {index}", "section_title": section_title}
            page_metadata.append(
                {
                    "page_number": index,
                    "extracted_chars": len(text),
                    "empty": False,
                    "ocr_attempted": ocr_attempted,
                    "section_title": section_title,
                    "locator": locator,
                }
            )
            page_segments.append(
                {
                    "segment_type": "pdf_page",
                    "segment_index": index - 1,
                    "section_title": section_title,
                    "text": rendered_page,
                    "locator": locator,
                }
            )
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
                "page_segments": page_segments,
                "ocr_enabled": self.ocr_enabled,
                "ocr_attempted_page_numbers": ocr_attempted_page_numbers,
            },
        )

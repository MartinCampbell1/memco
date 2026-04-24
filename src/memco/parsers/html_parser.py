from __future__ import annotations

from html import unescape
from html.parser import HTMLParser
from pathlib import Path

from memco.parsers.base import ParsedDocument


class _VisibleTextExtractor(HTMLParser):
    _BLOCK_TAGS = {
        "address",
        "article",
        "aside",
        "blockquote",
        "br",
        "dd",
        "div",
        "dl",
        "dt",
        "footer",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "header",
        "hr",
        "li",
        "main",
        "nav",
        "ol",
        "p",
        "pre",
        "section",
        "table",
        "td",
        "th",
        "tr",
        "ul",
    }
    _IGNORED_TAGS = {"script", "style", "noscript", "template"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._ignored_depth = 0
        self._in_title = False
        self._title_parts: list[str] = []
        self._text_parts: list[str] = []

    @property
    def title(self) -> str:
        return " ".join(" ".join(self._title_parts).split()).strip()

    @property
    def text(self) -> str:
        text = unescape("".join(self._text_parts))
        lines = [" ".join(line.split()).strip() for line in text.splitlines()]
        return "\n".join(line for line in lines if line)

    def handle_starttag(self, tag: str, attrs) -> None:
        normalized = tag.lower()
        if normalized in self._IGNORED_TAGS:
            self._ignored_depth += 1
        if normalized == "title":
            self._in_title = True
        if normalized in self._BLOCK_TAGS:
            self._text_parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        normalized = tag.lower()
        if normalized in self._IGNORED_TAGS and self._ignored_depth:
            self._ignored_depth -= 1
        if normalized == "title":
            self._in_title = False
        if normalized in self._BLOCK_TAGS:
            self._text_parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self._ignored_depth:
            return
        if self._in_title:
            self._title_parts.append(data)
            return
        self._text_parts.append(data)


class HtmlParser:
    def parse(self, path: Path) -> ParsedDocument:
        extractor = _VisibleTextExtractor()
        extractor.feed(path.read_text(encoding="utf-8", errors="ignore"))
        extractor.close()

        title = extractor.title or path.stem
        text = extractor.text
        parsed_text = f"# {title}\n\n{text}\n" if text else f"# {title}\n"
        return ParsedDocument(
            text=parsed_text,
            parser_name="html",
            confidence=0.9 if text else 0.4,
            metadata={"title": title},
        )

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
from pathlib import Path

from memco.parsers.base import ParsedDocument


_TELEGRAM_TITLE_DATE_RE = re.compile(
    r"(?P<date>\d{1,2}\.\d{1,2}\.\d{4})\s+"
    r"(?P<time>\d{1,2}:\d{2}(?::\d{2})?)"
    r"(?:\s+UTC(?P<offset>[+-]\d{2}:?\d{2})?)?",
    re.IGNORECASE,
)


def _normalize_text(value) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "".join(_normalize_text(item) for item in value)
    if isinstance(value, dict):
        return _normalize_text(value.get("text") or value.get("value") or "")
    return str(value)


def _parse_telegram_datetime(value: str) -> str:
    raw = value.strip()
    if not raw:
        return ""
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    if _TELEGRAM_TITLE_DATE_RE.search(raw):
        match = _TELEGRAM_TITLE_DATE_RE.search(raw)
        assert match is not None
        day, month, year = [int(piece) for piece in match.group("date").split(".")]
        time_parts = [int(piece) for piece in match.group("time").split(":")]
        hour, minute = time_parts[:2]
        second = time_parts[2] if len(time_parts) > 2 else 0
        tzinfo = timezone.utc
        offset = (match.group("offset") or "").replace(":", "")
        if offset:
            sign = 1 if offset.startswith("+") else -1
            hours = int(offset[1:3])
            minutes = int(offset[3:5])
            tzinfo = timezone(sign * timedelta(hours=hours, minutes=minutes))
        return (
            datetime(year, month, day, hour, minute, second, tzinfo=tzinfo)
            .astimezone(timezone.utc)
            .isoformat()
            .replace("+00:00", "Z")
        )
    try:
        parsed = datetime.fromisoformat(raw.replace(" ", "T"))
    except ValueError:
        return ""
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _message_line(message: dict[str, object]) -> str:
    header = " ".join(str(part).strip() for part in [message.get("timestamp"), message.get("speaker")] if str(part).strip())
    return f"{header}: {message['text']}".strip()


class _TelegramHtmlParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.messages: list[dict[str, object]] = []
        self._current: dict[str, object] | None = None
        self._message_depth = 0
        self._from_depth = 0
        self._text_depth = 0
        self._reply_depth = 0
        self._last_sender = ""

    @staticmethod
    def _classes(attrs: dict[str, str]) -> set[str]:
        return set((attrs.get("class") or "").split())

    def handle_starttag(self, tag: str, attrs_list) -> None:
        attrs = {str(key): str(value or "") for key, value in attrs_list}
        classes = self._classes(attrs)
        if tag.lower() == "div" and "message" in classes and self._current is None:
            self._current = {
                "role": "unknown",
                "speaker": "",
                "timestamp": "",
                "text": "",
                "meta": {"source_format": "telegram_html", "message_id": attrs.get("id", "")},
            }
            self._message_depth = 1
            return
        if self._current is not None and tag.lower() == "div":
            self._message_depth += 1
            if "from_name" in classes:
                self._from_depth += 1
            if "text" in classes:
                self._text_depth += 1
            if "reply_to" in classes:
                self._reply_depth += 1
            if "date" in classes and attrs.get("title"):
                self._current["timestamp"] = _parse_telegram_datetime(attrs["title"])
        elif self._current is not None and tag.lower() == "br" and self._text_depth:
            self._current["text"] = f"{self._current.get('text') or ''}\n"

    def handle_endtag(self, tag: str) -> None:
        if self._current is None or tag.lower() != "div":
            return
        if self._from_depth:
            self._from_depth -= 1
        if self._text_depth:
            self._text_depth -= 1
        if self._reply_depth:
            self._reply_depth -= 1
        self._message_depth -= 1
        if self._message_depth <= 0:
            text = " ".join(str(self._current.get("text") or "").split())
            speaker = " ".join(str(self._current.get("speaker") or "").split()) or self._last_sender
            if speaker:
                self._last_sender = speaker
            if text:
                self._current["speaker"] = speaker
                self._current["text"] = text
                self.messages.append(self._current)
            self._current = None

    def handle_data(self, data: str) -> None:
        if self._current is None:
            return
        if self._from_depth:
            self._current["speaker"] = f"{self._current.get('speaker') or ''} {data}".strip()
        elif self._text_depth:
            self._current["text"] = f"{self._current.get('text') or ''}{data}"
        elif self._reply_depth:
            meta = dict(self._current.get("meta") or {})
            reply_text = f"{meta.get('reply_preview') or ''} {data}".strip()
            meta["reply_preview"] = reply_text
            self._current["meta"] = meta


def _parse_json_export(path: Path) -> tuple[list[dict[str, object]], int]:
    data = json.loads(path.read_text(encoding="utf-8", errors="ignore"))
    raw_messages = data.get("messages") if isinstance(data, dict) else data
    if not isinstance(raw_messages, list):
        raise ValueError("Unsupported Telegram JSON export")
    messages: list[dict[str, object]] = []
    skipped = 0
    for item in raw_messages:
        if not isinstance(item, dict):
            skipped += 1
            continue
        if str(item.get("type") or "message") != "message":
            skipped += 1
            continue
        text = " ".join(_normalize_text(item.get("text") or item.get("text_entities") or "").split())
        if not text:
            skipped += 1
            continue
        meta = {"source_format": "telegram_json", "message_id": item.get("id", "")}
        if item.get("reply_to_message_id") is not None:
            meta["reply_to_message_id"] = item.get("reply_to_message_id")
        messages.append(
            {
                "role": "unknown",
                "speaker": str(item.get("from") or item.get("actor") or item.get("from_id") or "").strip(),
                "timestamp": _parse_telegram_datetime(str(item.get("date") or "")),
                "text": text,
                "meta": meta,
            }
        )
    return messages, skipped


def _parse_html_export(path: Path) -> tuple[list[dict[str, object]], int]:
    parser = _TelegramHtmlParser()
    parser.feed(path.read_text(encoding="utf-8", errors="ignore"))
    parser.close()
    return parser.messages, 0


class TelegramParser:
    def parse(self, path: Path) -> ParsedDocument:
        if path.suffix.lower() == ".json":
            messages, skipped = _parse_json_export(path)
            parser_kind = "telegram_json"
        else:
            messages, skipped = _parse_html_export(path)
            parser_kind = "telegram_html"
        lines = [_message_line(message) for message in messages if str(message.get("text") or "").strip()]
        return ParsedDocument(
            text="\n".join(lines).strip() + ("\n" if lines else ""),
            parser_name="telegram",
            confidence=0.95 if messages else 0.35,
            metadata={
                "messages": messages,
                "message_count": len(messages),
                "skipped_message_count": skipped,
                "parser_kind": parser_kind,
            },
        )

from __future__ import annotations

import re
from datetime import datetime, timezone, tzinfo
from pathlib import Path

from memco.parsers.base import ParsedDocument


_BRACKET_LINE_RE = re.compile(
    r"^\[(?P<date>\d{1,2}[/.]\d{1,2}[/.]\d{2,4}),\s*"
    r"(?P<time>\d{1,2}:\d{2}(?::\d{2})?(?:\s?[AP]M)?)\]\s+(?P<body>.*)$",
    re.IGNORECASE,
)
_DASH_LINE_RE = re.compile(
    r"^(?P<date>\d{1,2}[/.]\d{1,2}[/.]\d{2,4}),\s*"
    r"(?P<time>\d{1,2}:\d{2}(?::\d{2})?(?:\s?[AP]M)?)\s+-\s+(?P<body>.*)$",
    re.IGNORECASE,
)
_MEDIA_OMITTED_RE = re.compile(
    r"^(?:\u200e|\u202a|\u202c|\s)*(?:<media omitted>|image omitted|video omitted|audio omitted|sticker omitted|gif omitted|document omitted)",
    re.IGNORECASE,
)


def _parse_whatsapp_datetime(date_text: str, time_text: str, *, date_order: str, tz: tzinfo) -> str:
    separator = "." if "." in date_text else "/"
    pieces = [int(piece) for piece in date_text.split(separator)]
    if len(pieces) != 3:
        return ""
    first, second, year = pieces
    if year < 100:
        year += 2000 if year < 70 else 1900
    if date_order.upper() == "MDY":
        month, day = first, second
    else:
        day, month = first, second
    time_formats = ["%H:%M:%S", "%H:%M", "%I:%M:%S %p", "%I:%M %p"]
    normalized_time = " ".join(time_text.upper().replace("\u202f", " ").split())
    parsed_time = None
    for fmt in time_formats:
        try:
            parsed_time = datetime.strptime(normalized_time, fmt).time()
            break
        except ValueError:
            continue
    if parsed_time is None:
        return ""
    try:
        parsed = datetime(year, month, day, parsed_time.hour, parsed_time.minute, parsed_time.second, tzinfo=tz)
    except ValueError:
        return ""
    return parsed.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _split_sender_and_text(body: str) -> tuple[str, str] | None:
    # WhatsApp names can contain colons. Treat the final ": " separator as the
    # message boundary, which preserves names like "Alice: Work".
    if ": " not in body:
        return None
    speaker, text = body.rsplit(": ", 1)
    speaker = speaker.strip()
    text = text.strip()
    if not speaker or not text:
        return None
    return speaker, text


class WhatsAppParser:
    def __init__(self, *, date_order: str = "DMY", tz: tzinfo = timezone.utc) -> None:
        self.date_order = date_order
        self.tz = tz

    def parse(self, path: Path) -> ParsedDocument:
        messages: list[dict[str, object]] = []
        system_message_count = 0
        media_omitted_count = 0

        for raw_line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
            line = raw_line.strip()
            if not line:
                continue
            match = _BRACKET_LINE_RE.match(line) or _DASH_LINE_RE.match(line)
            if match is None:
                if messages:
                    messages[-1]["text"] = f"{messages[-1]['text']}\n{line}".strip()
                else:
                    system_message_count += 1
                continue

            body = match.group("body").strip()
            split = _split_sender_and_text(body)
            if split is None:
                system_message_count += 1
                continue
            speaker, text = split
            if _MEDIA_OMITTED_RE.match(text):
                media_omitted_count += 1
                continue
            occurred_at = _parse_whatsapp_datetime(
                match.group("date"),
                match.group("time"),
                date_order=self.date_order,
                tz=self.tz,
            )
            messages.append(
                {
                    "role": "unknown",
                    "speaker": speaker,
                    "timestamp": occurred_at,
                    "text": text,
                    "meta": {"source_format": "whatsapp"},
                }
            )

        lines = [
            f"{message['timestamp']} {message['speaker']}: {message['text']}".strip()
            for message in messages
            if str(message.get("text") or "").strip()
        ]
        confidence = 0.95 if messages else 0.35
        return ParsedDocument(
            text="\n".join(lines).strip() + ("\n" if lines else ""),
            parser_name="whatsapp",
            confidence=confidence,
            metadata={
                "messages": messages,
                "message_count": len(messages),
                "system_message_count": system_message_count,
                "media_omitted_count": media_omitted_count,
                "date_order": self.date_order,
                "timezone": "UTC" if self.tz == timezone.utc else str(self.tz),
            },
        )

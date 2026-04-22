from __future__ import annotations

import mailbox
from email import policy
from email.message import EmailMessage
from email.parser import BytesParser
from pathlib import Path

from memco.parsers.base import ParsedDocument


def _message_body(message: EmailMessage) -> str:
    if message.is_multipart():
        parts: list[str] = []
        for part in message.walk():
            if part.get_content_type() != "text/plain":
                continue
            disposition = str(part.get_content_disposition() or "")
            if disposition == "attachment":
                continue
            parts.append(str(part.get_content()).strip())
        return "\n\n".join(part for part in parts if part)
    payload = message.get_payload(decode=True)
    if isinstance(payload, bytes):
        charset = message.get_content_charset() or "utf-8"
        return payload.decode(charset, errors="ignore").strip()
    raw = message.get_payload()
    if isinstance(raw, str):
        return raw.strip()
    return str(raw or "").strip()


def _message_record(message: EmailMessage) -> dict[str, str]:
    subject = str(message.get("subject") or "").strip()
    sender = str(message.get("from") or "").strip()
    to = str(message.get("to") or "").strip()
    date = str(message.get("date") or "").strip()
    body = _message_body(message)
    return {
        "subject": subject,
        "from": sender,
        "to": to,
        "date": date,
        "body": body,
    }


def _render_message(record: dict[str, str], *, index: int) -> str:
    lines = [
        f"## Email {index}",
        f"Subject: {record['subject']}",
        f"From: {record['from']}",
        f"To: {record['to']}",
        f"Date: {record['date']}",
        "",
        record["body"],
    ]
    return "\n".join(lines).strip()


class EmailParser:
    def parse(self, path: Path) -> ParsedDocument:
        messages: list[dict[str, str]] = []
        if path.suffix.lower() == ".mbox":
            box = mailbox.mbox(str(path))
            for message in box:
                messages.append(_message_record(message))
        else:
            message = BytesParser(policy=policy.default).parsebytes(path.read_bytes())
            messages.append(_message_record(message))

        rendered = "\n\n".join(_render_message(record, index=index) for index, record in enumerate(messages, start=1))
        conversation_messages = [
            {
                "role": "email",
                "speaker": record["from"],
                "timestamp": record["date"],
                "text": record["body"],
                "meta": {
                    "subject": record["subject"],
                    "to": record["to"],
                    "parser_kind": "email",
                },
            }
            for record in messages
        ]
        metadata: dict[str, object] = {
            "message_count": len(messages),
            "messages": conversation_messages,
        }
        if messages:
            metadata.update(
                {
                    "subject": messages[0]["subject"],
                    "from": messages[0]["from"],
                    "to": messages[0]["to"],
                    "date": messages[0]["date"],
                }
            )
        return ParsedDocument(
            text=rendered.strip() + "\n",
            parser_name="email",
            confidence=0.95 if messages else 0.4,
            metadata=metadata,
        )

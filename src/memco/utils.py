from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def isoformat_z(value: datetime | None = None) -> str:
    current = value or datetime.now(timezone.utc)
    return current.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


def slugify(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value)
    ascii_only = normalized.encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", ascii_only).strip("-").lower()
    return slug or "item"


def chunk_text(text: str, max_chars: int = 2200) -> list[str]:
    normalized = text.strip()
    if not normalized:
        return []
    paragraphs = [paragraph.strip() for paragraph in normalized.split("\n\n") if paragraph.strip()]
    chunks: list[str] = []
    current: list[str] = []
    current_len = 0
    for paragraph in paragraphs:
        candidate_len = current_len + len(paragraph) + (2 if current else 0)
        if current and candidate_len > max_chars:
            chunks.append("\n\n".join(current))
            current = [paragraph]
            current_len = len(paragraph)
            continue
        current.append(paragraph)
        current_len = candidate_len
    if current:
        chunks.append("\n\n".join(current))
    return chunks


def chunk_text_by_tokens(text: str, *, max_tokens: int = 500, overlap_tokens: int = 50) -> list[str]:
    normalized = text.strip()
    if not normalized:
        return []
    words = normalized.split()
    budget = max(1, int(max_tokens))
    overlap = max(0, min(int(overlap_tokens), budget - 1))
    chunks: list[str] = []
    start = 0
    while start < len(words):
        end = min(len(words), start + budget)
        chunks.append(" ".join(words[start:end]))
        if end >= len(words):
            break
        start = max(end - overlap, start + 1)
    return chunks

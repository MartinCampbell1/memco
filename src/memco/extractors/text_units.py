from __future__ import annotations

import re
from dataclasses import replace

from memco.extractors.base import ExtractionContext


SENTENCE_BOUNDARY_RE = re.compile(r"(?<=[.!?])\s+")

_SOFT_BOUNDARY_RE = re.compile(r"\s*(?:;|,\s*but\b|\bbut\b|\band\b)\s+", re.IGNORECASE)

ASSERTION_START_RE = re.compile(
    r"(?ix)"
    r"^(?:"
    r"i\s+(?:currently\s+)?(?:live|work|prefer|like|love|use|know|attended|had|shipped|am|was|used\s+to)"
    r"|(?:currently\s+)?prefer\b"
    r"|used\s+to\b"
    r"|use\b"
    r"|my\s+(?:sister|brother|mother|father|wife|husband|partner|spouse|friend|best\s+friend|son|daughter)\b"
    r"|[A-Z][A-Za-z]*(?:\s+[A-Z][A-Za-z]*)?\s+"
    r"(?:lives|works|prefers|likes|uses|attended|had|shipped|is|was)\b"
    r"|in\s+\w+\s+\d{4},\s+i\s+(?:had|attended|shipped|worked|used)\b"
    r")"
)


def _normalize_unit(unit: str) -> str:
    return re.sub(r"\s+", " ", unit).strip(" \t\r\n;")


def _should_split_right(right: str) -> bool:
    return bool(ASSERTION_START_RE.match(_normalize_unit(right)))


def _split_soft(sentence: str) -> list[str]:
    remaining = sentence.strip()
    units: list[str] = []
    while remaining:
        match = _SOFT_BOUNDARY_RE.search(remaining)
        if match is None:
            units.append(remaining)
            break
        left = remaining[: match.start()]
        right = remaining[match.end() :]
        if not left.strip() or not _should_split_right(right):
            next_match = _SOFT_BOUNDARY_RE.search(remaining, match.end())
            if next_match is None:
                units.append(remaining)
                break
            prefix = remaining[: next_match.start()]
            suffix = remaining[next_match.end() :]
            if suffix.strip() and _should_split_right(suffix):
                units.append(prefix)
                remaining = suffix
                continue
            units.append(remaining)
            break
        units.append(left)
        remaining = right
    return units


def split_atomic_assertions(text: str) -> list[str]:
    """Split dense source text into assertion-sized units for extractors."""
    units: list[str] = []
    for sentence in SENTENCE_BOUNDARY_RE.split(text):
        normalized_sentence = _normalize_unit(sentence)
        if not normalized_sentence:
            continue
        for unit in _split_soft(normalized_sentence):
            normalized_unit = _normalize_unit(unit)
            if normalized_unit:
                units.append(normalized_unit)
    return units or [_normalize_unit(text)] if _normalize_unit(text) else []


def context_for_clause(context: ExtractionContext, clause: str) -> ExtractionContext:
    return replace(context, text=clause)

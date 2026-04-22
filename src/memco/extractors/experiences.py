from __future__ import annotations

import re

from memco.extractors.base import ExtractionContext, build_evidence, clean_value, review_reasons_for_context
from memco.utils import slugify


EXPERIENCE_PATTERNS = (
    re.compile(r"\bi\s+went\s+to\s+(?P<event>[^.!?\n]+)", re.IGNORECASE),
    re.compile(r"\bi\s+visited\s+(?P<event>[^.!?\n]+)", re.IGNORECASE),
    re.compile(r"\bi\s+attended\s+(?P<event>[^.!?\n]+)", re.IGNORECASE),
    re.compile(r"\bя\s+посетил(?:а)?\s+(?P<event>[^.!?\n]+)", re.IGNORECASE),
    re.compile(r"\bя\s+был(?:а)?\s+на\s+(?P<event>[^.!?\n]+)", re.IGNORECASE),
)


def extract(context: ExtractionContext) -> list[dict]:
    evidence = build_evidence(context)
    for pattern in EXPERIENCE_PATTERNS:
        match = pattern.search(context.text)
        if not match:
            continue
        raw_event = clean_value(match.group("event"))
        event = re.split(r"\s+with\s+|\s+in\s+\d{4}\b|\s+в\s+\d{4}\b|\s+and\s+it\s+was\s+", raw_event, maxsplit=1)[0].strip()
        if not event:
            continue
        review_reasons = review_reasons_for_context(context)
        participants = re.findall(r"\bwith\s+([A-Z][a-zA-Z0-9'\-]+)", context.text)
        temporal_match = re.search(r"\b(19|20)\d{2}\b", context.text)
        outcome_match = re.search(r"\bbecause\s+we\s+(?P<outcome>[^.!?\n]+)", context.text, re.IGNORECASE)
        lowered = context.text.lower()
        valence = "neutral"
        if any(marker in lowered for marker in ("great", "amazing", "wonderful", "won")):
            valence = "positive"
        elif any(marker in lowered for marker in ("awful", "bad", "terrible", "lost")):
            valence = "negative"
        return [
            {
                "domain": "experiences",
                "category": "event",
                "subcategory": "",
                "canonical_key": f"{context.subject_key}:experiences:event:{slugify(event)}",
                "payload": {
                    "event": event,
                    "summary": clean_value(context.text),
                    "participants": participants,
                    "event_at": temporal_match.group(0) if temporal_match else "",
                    "outcome": clean_value(outcome_match.group("outcome")) if outcome_match else "",
                    "valence": valence,
                },
                "summary": f"{context.subject_display} experienced {event}.",
                "confidence": 0.78 if context.person_id is not None else 0.55,
                "reason": ",".join(review_reasons),
                "needs_review": bool(review_reasons),
                "evidence": evidence,
            }
        ]
    return []

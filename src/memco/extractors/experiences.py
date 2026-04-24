from __future__ import annotations

import re

from memco.extractors.base import ExtractionContext, build_evidence, clean_value, review_reasons_for_context
from memco.utils import slugify


EXPERIENCE_PATTERNS = (
    re.compile(r"\bi\s+went\s+to\s+(?P<event>[^.!?\n]+)", re.IGNORECASE),
    re.compile(r"\bi\s+visited\s+(?P<event>[^.!?\n]+)", re.IGNORECASE),
    re.compile(r"\bi\s+attended\s+(?P<event>[^.!?\n]+)", re.IGNORECASE),
    re.compile(r"\bi\s+(?P<event>broke\s+up\s+with\s+[^.!?\n]+)", re.IGNORECASE),
    re.compile(r"\bi\s+(?P<event>moved\s+(?:to|from)\s+[^.!?\n]+)", re.IGNORECASE),
    re.compile(r"\bi\s+(?:had|got|suffered|experienced|started|ended|lost|won|launched|graduated)\s+(?P<event>[^.!?\n]+)", re.IGNORECASE),
    re.compile(r"\bi\s+was\s+injured(?:\s+(?P<event>[^.!?\n]+))?", re.IGNORECASE),
    re.compile(r"\bя\s+посетил(?:а)?\s+(?P<event>[^.!?\n]+)", re.IGNORECASE),
    re.compile(r"\bя\s+был(?:а)?\s+на\s+(?P<event>[^.!?\n]+)", re.IGNORECASE),
)

APPROXIMATE_YEAR_PATTERN = re.compile(
    r"\b(?:around|about|roughly|approximately|примерно|где-то)\s+(?P<year>(?:19|20)\d{2})\b",
    re.IGNORECASE,
)
RELATIVE_TEMPORAL_PATTERN = re.compile(
    r"\b(?P<anchor>last\s+(?:year|summer|winter|spring|fall|January|February|March|April|May|June|July|August|September|October|November|December)|this\s+(?:year|summer|winter|spring|fall)|"
    r"прошлым\s+(?:летом|годом|зимой|весной|осенью)|в\s+прошлом\s+году)\b",
    re.IGNORECASE,
)
MONTH_YEAR_PATTERN = re.compile(
    r"\b(?:(?:in|on|around)\s+)?(?P<month>January|February|March|April|May|June|July|August|September|October|November|December)\s+(?P<year>(?:19|20)\d{2})\b",
    re.IGNORECASE,
)
ISO_DATE_PATTERN = re.compile(r"\b(?P<date>(?:19|20)\d{2}-\d{2}-\d{2})\b")
YEAR_RANGE_PATTERN = re.compile(r"\bfrom\s+(?P<start>(?:19|20)\d{2})\s+(?:to|until|through)\s+(?P<end>(?:19|20)\d{2})\b", re.IGNORECASE)
NEGATED_OR_HYPOTHETICAL_RE = re.compile(
    r"\b(?:did\s+not|didn't|never|might|could|would|if\s+i|maybe|perhaps|не\s+|никогда|могу|может)\b",
    re.IGNORECASE,
)
MODAL_MAY_RE = re.compile(
    r"\bmay\s+(?:attend|visit|go|have|experience|suffer|get|start|end|lose|win|launch|graduate|move|be)\b"
)
NO_EVENT_DENIAL_RE = re.compile(
    r"\bi\s+(?:had|got|suffered|experienced)\s+no\s+(?:car\s+)?(?:accident|injury|event|breakup|promotion)\b",
    re.IGNORECASE,
)


def extract_temporal_anchor(text: str) -> dict[str, str]:
    iso_match = ISO_DATE_PATTERN.search(text)
    if iso_match:
        return {"event_at": iso_match.group("date"), "date_range": "", "temporal_anchor": iso_match.group("date")}
    range_match = YEAR_RANGE_PATTERN.search(text)
    if range_match:
        value = f"{range_match.group('start')} to {range_match.group('end')}"
        return {"event_at": "", "date_range": value, "temporal_anchor": value}
    month_match = MONTH_YEAR_PATTERN.search(text)
    if month_match:
        value = f"{month_match.group('month')} {month_match.group('year')}"
        return {"event_at": value, "date_range": "", "temporal_anchor": value}
    approximate_match = APPROXIMATE_YEAR_PATTERN.search(text)
    if approximate_match:
        return {"event_at": "", "date_range": "", "temporal_anchor": clean_value(approximate_match.group(0))}
    relative_match = RELATIVE_TEMPORAL_PATTERN.search(text)
    if relative_match:
        anchor = clean_value(relative_match.group("anchor"))
        return {"event_at": "", "date_range": "", "temporal_anchor": anchor}
    year_match = re.search(r"\b(19|20)\d{2}\b", text)
    if year_match:
        return {"event_at": year_match.group(0), "date_range": "", "temporal_anchor": year_match.group(0)}
    return {"event_at": "", "date_range": "", "temporal_anchor": ""}


def _event_text(raw_event: str) -> str:
    event = clean_value(raw_event)
    if event.lower().startswith("broke up with "):
        event = re.split(
            r"\s+in\s+\d{4}\b|\s+in\s+(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+(?:19|20)\d{2}\b",
            event,
            maxsplit=1,
            flags=re.IGNORECASE,
        )[0].strip()
        return event
    event = re.split(
        r"\s+during\s+|\s+with\s+|\s+in\s+\d{4}\b|\s+в\s+\d{4}\b|\s+(?:around|about|roughly|approximately)\s+\d{4}\b|"
        r"\s+in\s+(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+(?:19|20)\d{2}\b|"
        r"\s+(?:примерно|где-то)\s+в?\s*\d{4}\b|\s+and\s+it\s+was\s+|\s+and\s+i\s+had\s+to\s+",
        event,
        maxsplit=1,
        flags=re.IGNORECASE,
    )[0].strip()
    event = re.sub(r"^(?:a|an)\s+", "", event, flags=re.IGNORECASE)
    return event


def _location(text: str) -> str:
    match = re.search(r"\bto\s+the\s+(?P<location>[A-Z][A-Za-z0-9'\-]+(?:\s+[A-Z][A-Za-z0-9'\-]+)*)", text)
    return clean_value(match.group("location")) if match else ""


def _participants(text: str) -> list[str]:
    match = re.search(r"\bwith\s+(?P<people>[A-Z][a-zA-Z0-9'\-]+(?:\s*(?:,|and)\s*[A-Z][a-zA-Z0-9'\-]+)*)", text)
    if not match:
        return []
    return [
        clean_value(part)
        for part in re.split(r"\s*,\s*|\s+and\s+", match.group("people"))
        if clean_value(part)
    ]


def _linked_projects(text: str) -> list[str]:
    projects = re.findall(r"\b(Project\s+[A-Z][A-Za-z0-9'\-]+)\b", text)
    return list(dict.fromkeys(clean_value(project) for project in projects if clean_value(project)))


def _recurrence(text: str) -> str:
    match = re.search(r"\b(every\s+(?:day|week|month|year|summer|winter|spring|fall)|weekly|monthly|yearly|annually)\b", text, re.IGNORECASE)
    return clean_value(match.group(1)).lower() if match else ""


def _lesson(text: str) -> str:
    match = re.search(r"\bi\s+learned\s+to\s+(?P<lesson>[^.!?\n]+)", text, re.IGNORECASE)
    if not match:
        match = re.search(r"\b(?:lesson|takeaway)\s+was\s+(?P<lesson>[^.!?\n]+)", text, re.IGNORECASE)
    return clean_value(match.group("lesson")) if match else ""


def _event_hierarchy(text: str, event: str) -> list[str]:
    parent = ""
    project_match = re.search(r"\bduring\s+(?P<parent>Project\s+[A-Z][A-Za-z0-9'\-]+)\b", text)
    if project_match:
        parent = clean_value(project_match.group("parent"))
    if not parent:
        parent_match = re.search(
            r"\bduring\s+(?:a|an|the)?\s*(?P<parent>[^.!?\n]+?)(?:\s+to\s+the\s+|\s+with\s+|\s+in\s+|[.!?\n])",
            text,
            re.IGNORECASE,
        )
        if parent_match:
            parent = clean_value(parent_match.group("parent"))
    if parent:
        return [parent, event]
    return [event]


def _valence_and_intensity(text: str) -> tuple[str, float]:
    lowered = text.lower()
    if any(marker in lowered for marker in ("traumatic", "terrifying", "serious", "scary", "awful", "painful")):
        return "negative", 0.85
    if any(marker in lowered for marker in ("stressful", "bad", "lost")):
        return "negative", 0.6
    if any(marker in lowered for marker in ("great", "amazing", "wonderful", "won")):
        return "positive", 0.6
    return "neutral", 0.2


def extract(context: ExtractionContext) -> list[dict]:
    if (
        NEGATED_OR_HYPOTHETICAL_RE.search(context.text)
        or MODAL_MAY_RE.search(context.text)
        or NO_EVENT_DENIAL_RE.search(context.text)
    ):
        return []
    evidence = build_evidence(context)
    for pattern in EXPERIENCE_PATTERNS:
        match = pattern.search(context.text)
        if not match:
            continue
        raw_event = clean_value(match.group("event") or "injured")
        event = _event_text(raw_event)
        if not event:
            continue
        review_reasons = review_reasons_for_context(context)
        participants = _participants(context.text)
        temporal = extract_temporal_anchor(context.text)
        if event.lower().startswith("moved ") and not (temporal["event_at"] or temporal["temporal_anchor"]):
            continue
        outcome_match = re.search(r"\bbecause\s+we\s+(?P<outcome>[^.!?\n]+)", context.text, re.IGNORECASE)
        if not outcome_match:
            outcome_match = re.search(r"\bwe\s+(?P<outcome>won\s+[^.!?\n]+)", context.text, re.IGNORECASE)
        pause_match = re.search(r"\bi\s+had\s+to\s+(?P<outcome>pause\s+[^.!?\n]+)", context.text, re.IGNORECASE)
        valence, intensity = _valence_and_intensity(context.text)
        linked_projects = _linked_projects(context.text)
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
                    "event_at": temporal["event_at"],
                    "date_range": temporal["date_range"],
                    "temporal_anchor": temporal["temporal_anchor"],
                    "location": _location(context.text),
                    "outcome": clean_value((outcome_match.group("outcome") if outcome_match else "") or (pause_match.group("outcome") if pause_match else "")),
                    "lesson": _lesson(context.text),
                    "linked_persons": participants,
                    "linked_projects": linked_projects,
                    "recurrence": _recurrence(context.text),
                    "event_hierarchy": _event_hierarchy(context.text, event),
                    "valence": valence,
                    "intensity": intensity,
                },
                "summary": f"{context.subject_display} experienced {event}.",
                "confidence": 0.78 if context.person_id is not None else 0.55,
                "reason": ",".join(review_reasons),
                "needs_review": bool(review_reasons),
                "evidence": evidence,
            }
        ]
    return []

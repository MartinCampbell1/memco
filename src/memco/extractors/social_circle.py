from __future__ import annotations

import re

from memco.extractors.base import ExtractionContext, build_evidence, clean_value, review_reasons_for_context
from memco.utils import slugify


SOCIAL_PATTERN = re.compile(
    r"\b(?P<target>[a-zA-Z][a-zA-Z0-9'\- ]{0,80})\s+is\s+my\s+"
    r"(?P<relation>friend|brother|sister|wife|husband|partner|mother|father|mom|dad|son|daughter|colleague|boss|roommate|neighbor)\b",
    re.IGNORECASE,
)
SOCIAL_PATTERN_RU = re.compile(
    r"\b(?P<target>[a-zA-Z][a-zA-Z0-9'\- ]{0,80})\s+мой\s+(?P<relation>друг|брат|отец|муж|сын|партнер|коллега)\b"
    r"|\b(?P<target_alt>[a-zA-Z][a-zA-Z0-9'\- ]{0,80})\s+моя\s+(?P<relation_alt>сестра|мать|жена|дочь|партнерша)\b",
    re.IGNORECASE,
)

SOCIAL_PAST_PATTERN = re.compile(
    r"\b(?P<target>[a-zA-Z][a-zA-Z0-9'\- ]{0,80})\s+used\s+to\s+be\s+my\s+"
    r"(?P<relation>friend|brother|sister|wife|husband|partner|mother|father|mom|dad|son|daughter|colleague|boss|roommate|neighbor|manager)\b",
    re.IGNORECASE,
)
SOCIAL_PAST_PATTERN_RU = re.compile(
    r"\b(?P<target>[a-zA-Z][a-zA-Z0-9'\- ]{0,80})\s+раньше\s+был\s+моим\s+(?P<relation>другом|братом|отцом|мужем|сыном|партнером|коллегой|менеджером)\b",
    re.IGNORECASE,
)

RELATIONSHIP_EVENT_PATTERN = re.compile(
    r"\bi\s+(?P<event>met|reconnected with)\s+(?P<target>[A-Z][a-zA-Z0-9'\-]+)(?:\s+(?:at|in)\s+(?P<context>[^.!?\n]+))?",
    re.IGNORECASE,
)
RELATIONSHIP_EVENT_PATTERN_RU = re.compile(
    r"\bя\s+(?P<event>встретил(?:а)?|снова\s+увидел(?:а)?)\s+(?P<target>[A-Z][a-zA-Z0-9'\-]+)(?:\s+(?:на|в)\s+(?P<context>[^.!?\n]+))?",
    re.IGNORECASE,
)


def extract(context: ExtractionContext) -> list[dict]:
    event_match = RELATIONSHIP_EVENT_PATTERN.search(context.text)
    if event_match is None:
        event_match = RELATIONSHIP_EVENT_PATTERN_RU.search(context.text)
    if event_match:
        target_label = clean_value(event_match.group("target"))
        review_reasons = review_reasons_for_context(context)
        target_person_id = None
        if context.resolve_person_id is not None:
            target_person_id = context.resolve_person_id(target_label)
        if target_person_id is None:
            review_reasons.append("relation_target_unresolved")
        event_name = clean_value(event_match.group("event")).lower()
        if event_name.startswith("встрет"):
            event_name = "met"
        elif event_name.startswith("снова увид"):
            event_name = "reconnected with"
        return [
            {
                "domain": "social_circle",
                "category": "relationship_event",
                "subcategory": event_name.replace(" ", "_"),
                "canonical_key": f"{context.subject_key}:social_circle:relationship_event:{slugify(target_label)}:{slugify(event_name)}",
                "payload": {
                    "target_label": target_label,
                    "target_person_id": target_person_id,
                    "event": event_name,
                    "context": clean_value(event_match.group("context") or ""),
                },
                "summary": f"{context.subject_display} {event_name} {target_label}.",
                "confidence": 0.72 if not review_reasons else 0.5,
                "reason": ",".join(review_reasons),
                "needs_review": bool(review_reasons),
                "evidence": build_evidence(context),
            }
        ]

    match = SOCIAL_PATTERN.search(context.text)
    is_current = True
    if not match:
        match = SOCIAL_PAST_PATTERN.search(context.text)
        is_current = False
    if not match:
        match = SOCIAL_PATTERN_RU.search(context.text)
    if not match:
        match = SOCIAL_PAST_PATTERN_RU.search(context.text)
        is_current = False
    if not match:
        return []
    target_label = clean_value(match.groupdict().get("target") or match.groupdict().get("target_alt") or "")
    relation = clean_value(match.groupdict().get("relation") or match.groupdict().get("relation_alt") or "").lower()
    relation = {
        "друг": "friend",
        "другом": "friend",
        "брат": "brother",
        "братом": "brother",
        "сестра": "sister",
        "мать": "mother",
        "отец": "father",
        "отцом": "father",
        "жена": "wife",
        "муж": "husband",
        "мужем": "husband",
        "сын": "son",
        "сыном": "son",
        "дочь": "daughter",
        "партнер": "partner",
        "партнером": "partner",
        "партнерша": "partner",
        "коллега": "colleague",
        "коллегой": "colleague",
        "менеджером": "manager",
    }.get(relation, relation)
    review_reasons = review_reasons_for_context(context)
    target_person_id = None
    if context.resolve_person_id is not None:
        target_person_id = context.resolve_person_id(target_label)
    if target_person_id is None:
        review_reasons.append("relation_target_unresolved")
    return [
        {
            "domain": "social_circle",
            "category": relation,
            "subcategory": "",
            "canonical_key": f"{context.subject_key}:social_circle:{relation}:{slugify(target_label)}",
            "payload": {
                "relation": relation,
                "target_label": target_label,
                "target_person_id": target_person_id,
                "is_current": is_current,
            },
            "summary": f"{context.subject_display} says {target_label} is their {relation}.",
            "confidence": 0.8 if not review_reasons else 0.55,
            "reason": ",".join(review_reasons),
            "needs_review": bool(review_reasons),
            "evidence": build_evidence(context),
        }
    ]

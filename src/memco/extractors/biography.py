from __future__ import annotations

import re

from memco.extractors.base import ExtractionContext, build_evidence, clean_value, review_reasons_for_context
from memco.utils import slugify


RESIDENCE_PATTERNS = (
    re.compile(r"\bi\s+(?:currently\s+)?live\s+in\s+(?P<value>[^.!?\n]+)", re.IGNORECASE),
    re.compile(r"\bi\s+moved\s+to\s+(?P<value>[^.!?\n]+)", re.IGNORECASE),
    re.compile(r"\bi(?:'m| am)\s+based\s+in\s+(?P<value>[^.!?\n]+)", re.IGNORECASE),
    re.compile(r"\b(?P<value>[A-Z][^.!?\n]+?)\s+is\s+my\s+base(?:\s+these\s+days)?", re.IGNORECASE),
    re.compile(r"\bя\s+(?:сейчас\s+)?жив[ыу]\s+в\s+(?P<value>[^.!?\n]+)", re.IGNORECASE),
    re.compile(r"\bя\s+переехал(?:а|и)?\s+в\s+(?P<value>[^.!?\n]+)", re.IGNORECASE),
)

UNCERTAIN_RESIDENCE_PATTERNS = (
    re.compile(r"\bi\s+(?:might|may|could)\s+move\s+to\s+(?P<value>[^.!?\n]+)", re.IGNORECASE),
    re.compile(r"\bi(?:'m| am)\s+(?:thinking about|considering)\s+moving\s+to\s+(?P<value>[^.!?\n]+)", re.IGNORECASE),
    re.compile(r"\bя\s+(?:возможно|может\s+быть)\s+переед[уе]\s+в\s+(?P<value>[^.!?\n]+)", re.IGNORECASE),
)

ORIGIN_PATTERNS = (
    re.compile(r"\bi(?:'m| am)\s+from\s+(?P<value>[^.!?\n]+)", re.IGNORECASE),
    re.compile(r"\bя\s+из\s+(?P<value>[^.!?\n]+)", re.IGNORECASE),
)

LANGUAGE_PATTERNS = (
    re.compile(r"\bi\s+speak\s+(?P<value>[^.!?\n]+)", re.IGNORECASE),
    re.compile(r"\bя\s+говорю\s+на\s+(?P<value>[^.!?\n]+)", re.IGNORECASE),
)

PET_PATTERNS = (
    re.compile(r"\bmy\s+(?P<pet_type>dog|cat|pet)\s+is\s+(?P<pet_name>[^.!?\n]+)", re.IGNORECASE),
)

GOAL_PATTERNS = (
    re.compile(r"\bmy\s+goal\s+is\s+to\s+(?P<value>[^.!?\n]+)", re.IGNORECASE),
    re.compile(r"\bмоя\s+цель\s+[—-]?\s*(?P<value>[^.!?\n]+)", re.IGNORECASE),
)

IDENTITY_PATTERNS = (
    re.compile(r"\bmy\s+name\s+is\s+(?P<value>[^.!?\n]+)", re.IGNORECASE),
    re.compile(r"\bменя\s+зовут\s+(?P<value>[^.!?\n]+)", re.IGNORECASE),
)

EDUCATION_PATTERNS = (
    re.compile(r"\bi\s+studied\s+(?P<field>[^.!?\n]+?)\s+at\s+(?P<institution>[^.!?\n]+)", re.IGNORECASE),
    re.compile(r"\bя\s+учил(?:ся|ась)\s+на\s+(?P<field>[^.!?\n]+?)\s+в\s+(?P<institution>[^.!?\n]+)", re.IGNORECASE),
)

FAMILY_PATTERNS = (
    re.compile(r"\bmy\s+(?P<relation>mother|father|sister|brother|son|daughter|wife|husband|partner)\s+is\s+(?P<name>[^.!?\n]+)", re.IGNORECASE),
    re.compile(r"\bмоя\s+(?P<relation>сестра|мать|жена|дочь|партнерша)\s+[—-]?\s*(?P<name>[^.!?\n]+)", re.IGNORECASE),
    re.compile(r"\bмой\s+(?P<relation>брат|отец|муж|сын|партнер)\s+[—-]?\s*(?P<name>[^.!?\n]+)", re.IGNORECASE),
)

HABIT_PATTERNS = (
    re.compile(r"\bi\s+(?:usually|always)\s+(?P<value>[^.!?\n]+)", re.IGNORECASE),
    re.compile(r"\bя\s+обычно\s+(?P<value>[^.!?\n]+)", re.IGNORECASE),
)

CONSTRAINT_PATTERNS = (
    re.compile(r"\bi\s+can(?:not|'t)\s+(?P<value>[^.!?\n]+)", re.IGNORECASE),
    re.compile(r"\bi\s+must\s+avoid\s+(?P<value>[^.!?\n]+)", re.IGNORECASE),
    re.compile(r"\bя\s+не\s+могу\s+(?P<value>[^.!?\n]+)", re.IGNORECASE),
    re.compile(r"\bмне\s+нельзя\s+(?P<value>[^.!?\n]+)", re.IGNORECASE),
)


def _with_review_reasons(context: ExtractionContext, *extra_reasons: str) -> list[str]:
    reasons = review_reasons_for_context(context)
    for reason in extra_reasons:
        if reason and reason not in reasons:
            reasons.append(reason)
    return reasons


def _clean_residence_value(raw: str) -> tuple[str, str, list[str]]:
    value = clean_value(raw)
    reasons: list[str] = []
    value = re.split(r"\s+(?:and|but)\s+i\s+", value, maxsplit=1, flags=re.IGNORECASE)[0]
    value = re.split(r"\s+(?:because|where)\s+", value, maxsplit=1, flags=re.IGNORECASE)[0]
    valid_from = ""
    year_match = re.search(r"\s+(?:in|since)\s+((?:19|20)\d{2})\b.*$", value, re.IGNORECASE)
    if year_match:
        valid_from = year_match.group(1)
        value = value[: year_match.start()]
    city = clean_value(value)
    lowered = city.lower()
    if re.search(r"\b(?:and|prefer|work|moved|since|in\s+(?:19|20)\d{2})\b", lowered):
        reasons.append("suspicious_residence_payload")
    if len(city.split()) > 4:
        reasons.append("suspicious_residence_payload")
    return city, valid_from, reasons


def _clean_identity_name(raw: str) -> tuple[str, list[str]]:
    value = clean_value(raw)
    value = re.split(r"\s+(?:and|but)\s+i\s+", value, maxsplit=1, flags=re.IGNORECASE)[0]
    name = clean_value(value).title()
    lowered = name.lower()
    reasons: list[str] = []
    if re.search(r"\b(?:moved|work|works|love|prefer|live|based)\b", lowered):
        reasons.append("suspicious_identity_payload")
    if len(name.split()) > 4:
        reasons.append("suspicious_identity_payload")
    return name, reasons


def extract(context: ExtractionContext) -> list[dict]:
    candidates: list[dict] = []
    evidence = build_evidence(context)
    residence_is_uncertain = any(pattern.search(context.text) for pattern in UNCERTAIN_RESIDENCE_PATTERNS)
    for pattern in RESIDENCE_PATTERNS:
        match = pattern.search(context.text)
        if not match:
            continue
        if residence_is_uncertain:
            break
        city, valid_from, quality_reasons = _clean_residence_value(match.group("value"))
        if not city:
            continue
        review_reasons = _with_review_reasons(context, *quality_reasons)
        payload = {"city": city}
        if valid_from:
            payload["valid_from"] = valid_from
        candidates.append(
            {
                "domain": "biography",
                "category": "residence",
                "subcategory": "",
                "canonical_key": f"{context.subject_key}:biography:residence:{slugify(city)}",
                "payload": payload,
                "summary": f"{context.subject_display} lives in {city}.",
                "confidence": 0.9 if context.person_id is not None else 0.65,
                "reason": ",".join(review_reasons),
                "needs_review": bool(review_reasons),
                "evidence": evidence,
            }
        )
        break

    for pattern in ORIGIN_PATTERNS:
        match = pattern.search(context.text)
        if not match:
            continue
        place = clean_value(match.group("value"))
        if not place:
            continue
        review_reasons = review_reasons_for_context(context)
        candidates.append(
            {
                "domain": "biography",
                "category": "origin",
                "subcategory": "",
                "canonical_key": f"{context.subject_key}:biography:origin:{slugify(place)}",
                "payload": {"place": place},
                "summary": f"{context.subject_display} is from {place}.",
                "confidence": 0.82 if context.person_id is not None else 0.58,
                "reason": ",".join(review_reasons),
                "needs_review": bool(review_reasons),
                "evidence": evidence,
            }
        )
        break

    for pattern in LANGUAGE_PATTERNS:
        match = pattern.search(context.text)
        if not match:
            continue
        raw = clean_value(match.group("value"))
        if not raw:
            continue
        languages = [part.strip().title() for part in re.split(r",| and ", raw) if part.strip()]
        review_reasons = review_reasons_for_context(context)
        candidates.append(
            {
                "domain": "biography",
                "category": "languages",
                "subcategory": "",
                "canonical_key": f"{context.subject_key}:biography:languages:{slugify('-'.join(languages))}",
                "payload": {"languages": languages},
                "summary": f"{context.subject_display} speaks {', '.join(languages)}.",
                "confidence": 0.8 if context.person_id is not None else 0.56,
                "reason": ",".join(review_reasons),
                "needs_review": bool(review_reasons),
                "evidence": evidence,
            }
        )
        break

    for pattern in PET_PATTERNS:
        match = pattern.search(context.text)
        if not match:
            continue
        pet_type = clean_value(match.group("pet_type")).lower()
        pet_name = clean_value(match.group("pet_name")).title()
        review_reasons = review_reasons_for_context(context)
        candidates.append(
            {
                "domain": "biography",
                "category": "pets",
                "subcategory": "",
                "canonical_key": f"{context.subject_key}:biography:pets:{slugify(pet_type)}:{slugify(pet_name)}",
                "payload": {"pet_type": pet_type, "pet_name": pet_name},
                "summary": f"{context.subject_display} has a {pet_type} named {pet_name}.",
                "confidence": 0.78 if context.person_id is not None else 0.54,
                "reason": ",".join(review_reasons),
                "needs_review": bool(review_reasons),
                "evidence": evidence,
            }
        )
        break

    for pattern in GOAL_PATTERNS:
        match = pattern.search(context.text)
        if not match:
            continue
        goal = clean_value(match.group("value"))
        if not goal:
            continue
        review_reasons = review_reasons_for_context(context)
        candidates.append(
            {
                "domain": "biography",
                "category": "goals",
                "subcategory": "",
                "canonical_key": f"{context.subject_key}:biography:goals:{slugify(goal)}",
                "payload": {"goal": goal},
                "summary": f"{context.subject_display}'s goal is to {goal}.",
                "confidence": 0.76 if context.person_id is not None else 0.52,
                "reason": ",".join(review_reasons),
                "needs_review": bool(review_reasons),
                "evidence": evidence,
            }
        )
        break

    for pattern in IDENTITY_PATTERNS:
        match = pattern.search(context.text)
        if not match:
            continue
        name, quality_reasons = _clean_identity_name(match.group("value"))
        if not name:
            continue
        review_reasons = _with_review_reasons(context, *quality_reasons)
        candidates.append(
            {
                "domain": "biography",
                "category": "identity",
                "subcategory": "",
                "canonical_key": f"{context.subject_key}:biography:identity:{slugify(name)}",
                "payload": {"name": name},
                "summary": f"{context.subject_display}'s name is {name}.",
                "confidence": 0.88 if context.person_id is not None else 0.62,
                "reason": ",".join(review_reasons),
                "needs_review": bool(review_reasons),
                "evidence": evidence,
            }
        )
        break

    for pattern in EDUCATION_PATTERNS:
        match = pattern.search(context.text)
        if not match:
            continue
        field = clean_value(match.group("field"))
        institution = clean_value(match.group("institution"))
        if not field or not institution:
            continue
        review_reasons = review_reasons_for_context(context)
        candidates.append(
            {
                "domain": "biography",
                "category": "education",
                "subcategory": "",
                "canonical_key": f"{context.subject_key}:biography:education:{slugify(institution)}:{slugify(field)}",
                "payload": {"institution": institution, "field": field},
                "summary": f"{context.subject_display} studied {field} at {institution}.",
                "confidence": 0.8 if context.person_id is not None else 0.56,
                "reason": ",".join(review_reasons),
                "needs_review": bool(review_reasons),
                "evidence": evidence,
            }
        )
        break

    for pattern in FAMILY_PATTERNS:
        match = pattern.search(context.text)
        if not match:
            continue
        relation = clean_value(match.group("relation")).lower()
        name = clean_value(match.group("name")).title()
        review_reasons = review_reasons_for_context(context)
        candidates.append(
            {
                "domain": "biography",
                "category": "family",
                "subcategory": relation,
                "canonical_key": f"{context.subject_key}:biography:family:{relation}:{slugify(name)}",
                "payload": {"relation": relation, "name": name},
                "summary": f"{context.subject_display}'s {relation} is {name}.",
                "confidence": 0.8 if context.person_id is not None else 0.56,
                "reason": ",".join(review_reasons),
                "needs_review": bool(review_reasons),
                "evidence": evidence,
            }
        )
        break

    for pattern in HABIT_PATTERNS:
        match = pattern.search(context.text)
        if not match:
            continue
        habit = clean_value(match.group("value"))
        if not habit:
            continue
        review_reasons = review_reasons_for_context(context)
        candidates.append(
            {
                "domain": "biography",
                "category": "habits",
                "subcategory": "",
                "canonical_key": f"{context.subject_key}:biography:habits:{slugify(habit)}",
                "payload": {"habit": habit},
                "summary": f"{context.subject_display} usually {habit}.",
                "confidence": 0.74 if context.person_id is not None else 0.5,
                "reason": ",".join(review_reasons),
                "needs_review": bool(review_reasons),
                "evidence": evidence,
            }
        )
        break

    for pattern in CONSTRAINT_PATTERNS:
        match = pattern.search(context.text)
        if not match:
            continue
        constraint = clean_value(match.group("value"))
        if not constraint:
            continue
        review_reasons = review_reasons_for_context(context)
        candidates.append(
            {
                "domain": "biography",
                "category": "constraints",
                "subcategory": "",
                "canonical_key": f"{context.subject_key}:biography:constraints:{slugify(constraint)}",
                "payload": {"constraint": constraint},
                "summary": f"{context.subject_display} has a constraint: {constraint}.",
                "confidence": 0.74 if context.person_id is not None else 0.5,
                "reason": ",".join(review_reasons),
                "needs_review": bool(review_reasons),
                "evidence": evidence,
            }
        )
        break

    return candidates

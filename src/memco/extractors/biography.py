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

AGE_BIRTH_PATTERNS = (
    re.compile(r"\bi\s+was\s+born\s+(?:on\s+)?(?:in\s+)?(?P<value>[^.!?\n]+)", re.IGNORECASE),
    re.compile(r"\bi(?:'m| am)\s+(?P<value>\d{1,3})\s+years?\s+old", re.IGNORECASE),
)

HEALTH_PATTERNS = (
    re.compile(r"\bi\s+have\s+(?P<value>[^.!?\n]+)", re.IGNORECASE),
    re.compile(r"\bi\s+was\s+diagnosed\s+with\s+(?P<value>[^.!?\n]+)", re.IGNORECASE),
    re.compile(r"\bi(?:'m| am)\s+allergic\s+to\s+(?P<value>[^.!?\n]+)", re.IGNORECASE),
)

VALUES_PATTERNS = (
    re.compile(r"\bi\s+value\s+(?P<value>[^.!?\n]+?)(?:\s+in\s+(?P<context>[^.!?\n]+?))?(?=$|[.!?\n])", re.IGNORECASE),
    re.compile(r"\bmy\s+core\s+value\s+is\s+(?P<value>[^.!?\n]+)", re.IGNORECASE),
)

FINANCES_PATTERNS = (
    re.compile(r"\bmy\s+financial\s+note\s+is\s+(?P<value>[^.!?\n]+)", re.IGNORECASE),
    re.compile(r"\bi\s+keep\s+(?P<value>an?\s+emergency\s+fund[^.!?\n]+)", re.IGNORECASE),
    re.compile(r"\bi\s+prefer\s+(?P<value>conservative\s+budgets?[^.!?\n]*)", re.IGNORECASE),
)

LEGAL_PATTERNS = (
    re.compile(r"\bmy\s+legal\s+note\s+is\s+(?P<value>[^.!?\n]+)", re.IGNORECASE),
    re.compile(r"\bmy\s+lawyer\s+is\s+(?P<value>[^.!?\n]+)", re.IGNORECASE),
    re.compile(r"\bi\s+keep\s+(?P<value>contracts?\s+private[^.!?\n]*)", re.IGNORECASE),
)

TRAVEL_HISTORY_PATTERNS = (
    re.compile(r"\bi\s+traveled\s+to\s+(?P<location>[^.!?\n]+?)(?:\s+in\s+(?P<event_at>(?:19|20)\d{2}))?(?=$|[.!?\n])", re.IGNORECASE),
    re.compile(r"\bi\s+visited\s+(?P<location>[^.!?\n]+?)(?:\s+in\s+(?P<event_at>(?:19|20)\d{2}))?(?=$|[.!?\n])", re.IGNORECASE),
)

LIFE_MILESTONE_PATTERNS = (
    re.compile(r"\bi\s+(?P<milestone>got\s+married|graduated|became\s+a\s+parent)(?:\s+in\s+(?P<event_at>(?:19|20)\d{2}))?(?=$|[.!?\n])", re.IGNORECASE),
    re.compile(r"\bmy\s+life\s+milestone\s+was\s+(?P<milestone>[^.!?\n]+?)(?:\s+in\s+(?P<event_at>(?:19|20)\d{2}))?(?=$|[.!?\n])", re.IGNORECASE),
)

COMMUNICATION_PREFERENCE_PATTERNS = (
    re.compile(r"\bplease\s+send\s+me\s+(?P<preference>[^.!?\n]+?)(?:\s+in\s+(?P<language>[A-Z][A-Za-z]+))?(?=$|[.!?\n])", re.IGNORECASE),
    re.compile(r"\bi\s+prefer\s+(?P<preference>short\s+direct\s+updates|voice\s+notes|written\s+summaries)(?:\s+in\s+(?P<language>[A-Z][A-Za-z]+))?(?=$|[.!?\n])", re.IGNORECASE),
)

OTHER_STABLE_PATTERNS = (
    re.compile(r"\bmy\s+passport\s+is\s+in\s+(?P<value>[^.!?\n]+)", re.IGNORECASE),
    re.compile(r"\bi\s+keep\s+my\s+passport\s+in\s+(?P<value>[^.!?\n]+)", re.IGNORECASE),
    re.compile(r"\bmy\s+backup\s+codes\s+are\s+in\s+(?P<value>[^.!?\n]+)", re.IGNORECASE),
)

HYPOTHETICAL_RE = re.compile(
    r"\b(?:might|may|could|would|if\s+(?:i|my)|maybe|perhaps|considering|thinking\s+about)\b",
    re.IGNORECASE,
)


def _with_review_reasons(context: ExtractionContext, *extra_reasons: str) -> list[str]:
    reasons = review_reasons_for_context(context)
    for reason in extra_reasons:
        if reason and reason not in reasons:
            reasons.append(reason)
    return reasons


def _candidate(
    context: ExtractionContext,
    *,
    category: str,
    subcategory: str = "",
    key: str,
    payload: dict,
    summary: str,
    confidence: float,
) -> dict:
    review_reasons = review_reasons_for_context(context)
    return {
        "domain": "biography",
        "category": category,
        "subcategory": subcategory,
        "canonical_key": f"{context.subject_key}:biography:{category}:{slugify(key)}",
        "payload": payload,
        "summary": summary,
        "confidence": confidence if context.person_id is not None else max(0.48, confidence - 0.24),
        "reason": ",".join(review_reasons),
        "needs_review": bool(review_reasons),
        "evidence": build_evidence(context),
    }


def _negated_or_hypothetical(text: str) -> bool:
    return bool(HYPOTHETICAL_RE.search(text) or re.search(r"\b(?:do\s+not|don't|not|never|no\s+longer)\b", text, re.IGNORECASE))


def _starts_negated(value: str) -> bool:
    return clean_value(value).lower().startswith(("not ", "no "))


def _year_or_date(value: str) -> str:
    match = re.search(r"\b((?:19|20)\d{2}(?:-\d{2}-\d{2})?)\b", value)
    return match.group(1) if match else clean_value(value)


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
    stable_blocked = _negated_or_hypothetical(context.text)
    residence_is_uncertain = any(pattern.search(context.text) for pattern in UNCERTAIN_RESIDENCE_PATTERNS)
    for pattern in RESIDENCE_PATTERNS:
        match = pattern.search(context.text)
        if not match:
            continue
        if residence_is_uncertain or stable_blocked:
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
        if stable_blocked:
            break
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
        if stable_blocked:
            break
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
        if stable_blocked:
            break
        pet_type = clean_value(match.group("pet_type")).lower()
        pet_name = clean_value(match.group("pet_name")).title()
        if _starts_negated(pet_name):
            continue
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
        if stable_blocked:
            break
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
        if stable_blocked:
            break
        name, quality_reasons = _clean_identity_name(match.group("value"))
        if not name or _starts_negated(name):
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
        if stable_blocked:
            break
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
        if stable_blocked:
            break
        relation = clean_value(match.group("relation")).lower()
        name = clean_value(match.group("name")).title()
        if _starts_negated(name):
            continue
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
        if stable_blocked:
            break
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
        if stable_blocked:
            break
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

    if not stable_blocked:
        for pattern in AGE_BIRTH_PATTERNS:
            match = pattern.search(context.text)
            if not match:
                continue
            value = clean_value(match.group("value"))
            if not value or _starts_negated(value):
                continue
            payload = {"age": value} if value.isdigit() and "born" not in context.text.lower() else {"birth_year": _year_or_date(value)}
            candidates.append(
                _candidate(
                    context,
                    category="age_birth",
                    key=next(iter(payload.values())),
                    payload=payload,
                    summary=f"{context.subject_display} has age/birth information: {next(iter(payload.values()))}.",
                    confidence=0.78,
                )
            )
            break

        for pattern in HEALTH_PATTERNS:
            match = pattern.search(context.text)
            if not match:
                continue
            health_fact = clean_value(match.group("value"))
            if not health_fact or _starts_negated(health_fact):
                continue
            if not re.search(r"\b(?:asthma|diabetes|migraine|migraines|allergy|allergic|gluten|surgery|injury|injured|diagnosed|anxiety|insomnia|condition)\b", health_fact, re.IGNORECASE):
                continue
            candidates.append(
                _candidate(
                    context,
                    category="health",
                    key=health_fact,
                    payload={"health_fact": health_fact, "status": "current"},
                    summary=f"{context.subject_display} has a health note: {health_fact}.",
                    confidence=0.72,
                )
            )
            break

        for pattern in VALUES_PATTERNS:
            match = pattern.search(context.text)
            if not match:
                continue
            value = clean_value(match.group("value"))
            if not value or _starts_negated(value):
                continue
            context_value = clean_value(match.groupdict().get("context") or "")
            payload = {"value": value}
            if context_value:
                payload["context"] = context_value
            candidates.append(
                _candidate(
                    context,
                    category="values",
                    key=f"{value}:{context_value}",
                    payload=payload,
                    summary=f"{context.subject_display} values {value}.",
                    confidence=0.72,
                )
            )
            break

        for pattern in FINANCES_PATTERNS:
            match = pattern.search(context.text)
            if not match:
                continue
            financial_note = clean_value(match.group("value"))
            if not financial_note or _starts_negated(financial_note):
                continue
            candidates.append(
                _candidate(
                    context,
                    category="finances",
                    key=financial_note,
                    payload={"financial_note": financial_note, "caution": "sensitive"},
                    summary=f"{context.subject_display} has a financial note: {financial_note}.",
                    confidence=0.68,
                )
            )
            break

        for pattern in LEGAL_PATTERNS:
            match = pattern.search(context.text)
            if not match:
                continue
            legal_note = clean_value(match.group("value"))
            if not legal_note or _starts_negated(legal_note):
                continue
            candidates.append(
                _candidate(
                    context,
                    category="legal",
                    key=legal_note,
                    payload={"legal_note": legal_note, "caution": "sensitive"},
                    summary=f"{context.subject_display} has a legal note: {legal_note}.",
                    confidence=0.68,
                )
            )
            break

        for pattern in TRAVEL_HISTORY_PATTERNS:
            match = pattern.search(context.text)
            if not match:
                continue
            location = clean_value(match.group("location"))
            if not location or _starts_negated(location):
                continue
            event_at = clean_value(match.groupdict().get("event_at") or "")
            payload = {"location": location}
            if event_at:
                payload["event_at"] = event_at
                payload["date_range"] = event_at
            candidates.append(
                _candidate(
                    context,
                    category="travel_history",
                    key=f"{location}:{event_at}",
                    payload=payload,
                    summary=f"{context.subject_display} traveled to {location}.",
                    confidence=0.72,
                )
            )
            break

        for pattern in LIFE_MILESTONE_PATTERNS:
            match = pattern.search(context.text)
            if not match:
                continue
            milestone = clean_value(match.group("milestone"))
            if not milestone or _starts_negated(milestone):
                continue
            event_at = clean_value(match.groupdict().get("event_at") or "")
            payload = {"milestone": milestone}
            if event_at:
                payload["event_at"] = event_at
            candidates.append(
                _candidate(
                    context,
                    category="life_milestone",
                    key=f"{milestone}:{event_at}",
                    payload=payload,
                    summary=f"{context.subject_display} has a life milestone: {milestone}.",
                    confidence=0.72,
                )
            )
            break

        for pattern in COMMUNICATION_PREFERENCE_PATTERNS:
            match = pattern.search(context.text)
            if not match:
                continue
            preference = clean_value(match.group("preference"))
            if not preference or _starts_negated(preference):
                continue
            language = clean_value(match.groupdict().get("language") or "")
            payload = {"preference": preference}
            if language:
                payload["language"] = language.title()
            payload["context"] = "communication"
            candidates.append(
                _candidate(
                    context,
                    category="communication_preference",
                    key=f"{preference}:{language}",
                    payload=payload,
                    summary=f"{context.subject_display} prefers {preference} for communication.",
                    confidence=0.74,
                )
            )
            break

        for pattern in OTHER_STABLE_PATTERNS:
            match = pattern.search(context.text)
            if not match:
                continue
            value = clean_value(match.group("value"))
            if not value or _starts_negated(value):
                continue
            fact = f"passport is in {value}" if "passport" in context.text.lower() else f"backup codes are in {value}"
            candidates.append(
                _candidate(
                    context,
                    category="other_stable_self_knowledge",
                    key=fact,
                    payload={"fact": fact, "context": "private note"},
                    summary=f"{context.subject_display} has a stable private note: {fact}.",
                    confidence=0.7,
                )
            )
            break

    return candidates

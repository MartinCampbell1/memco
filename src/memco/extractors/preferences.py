from __future__ import annotations

import re

from memco.extractors.base import ExtractionContext, build_evidence, clean_value, review_reasons_for_context
from memco.utils import slugify


PREFERENCE_PATTERNS = (
    ("dislike", re.compile(r"\bi\s+do\s+not\s+like\s+(?P<value>[^.!?\n]+?)(?:\s+because\s+(?P<reason>[^.!?\n]+))?(?=$|[.!?\n])", re.IGNORECASE)),
    ("dislike", re.compile(r"\bi\s+don't\s+like\s+(?P<value>[^.!?\n]+?)(?:\s+because\s+(?P<reason>[^.!?\n]+))?(?=$|[.!?\n])", re.IGNORECASE)),
    ("dislike", re.compile(r"\bi\s+(?P<strongly>strongly\s+)?dislike\s+(?P<value>[^.!?\n]+?)(?:\s+because\s+(?P<reason>[^.!?\n]+))?(?=$|[.!?\n])", re.IGNORECASE)),
    ("prefer", re.compile(r"\bi\s+(?:currently\s+)?prefer\s+(?P<value>[^.!?\n,]+?)(?=\s*,?\s+but\s+i\s+used\s+to\b|$|[.!?\n])", re.IGNORECASE)),
    ("like", re.compile(r"\bi\s+(?:currently\s+)?like\s+(?P<value>[^.!?\n,]+?)(?=\s*,?\s+but\s+i\s+used\s+to\b|$|[.!?\n])", re.IGNORECASE)),
    ("prefer", re.compile(r"\bi\s+now\s+prefer\s+(?P<value>[^.!?\n]+)", re.IGNORECASE)),
    ("prefer", re.compile(r"\bi\s+prefer\s+(?P<value>[^.!?\n]+)", re.IGNORECASE)),
    ("like", re.compile(r"\bi\s+love\s+(?P<value>[^.!?\n]+)", re.IGNORECASE)),
    ("like", re.compile(r"\bi\s+like\s+(?P<value>[^.!?\n]+)", re.IGNORECASE)),
    (
        "like",
        re.compile(
            r"\b(?P<value>[A-Za-z][^.!?\n]+?)\s+is\s+my\s+go-to\s+(?P<preference_category>drink|snack|meal|food|tool)\b"
            r"(?:\s+when\s+(?P<context>[^.!?\n]+))?",
            re.IGNORECASE,
        ),
    ),
    ("past_like", re.compile(r"\bi\s+used\s+to\s+like\s+(?P<value>[^.!?\n]+)", re.IGNORECASE)),
    ("past_prefer", re.compile(r"\bi\s+used\s+to\s+prefer\s+(?P<value>[^.!?\n]+)", re.IGNORECASE)),
    ("past_dislike", re.compile(r"\bi\s+used\s+to\s+dislike\s+(?P<value>[^.!?\n]+)", re.IGNORECASE)),
    ("prefer", re.compile(r"\bя\s+предпочитаю\s+(?P<value>[^.!?\n]+)", re.IGNORECASE)),
    ("like", re.compile(r"\bмне\s+нрав(?:ится|ят)\s+(?P<value>[^.!?\n]+)", re.IGNORECASE)),
    ("dislike", re.compile(r"\bя\s+(?P<strongly>очень\s+)?не\s+люблю\s+(?P<value>[^.!?\n]+?)(?:\s+потому\s+что\s+(?P<reason>[^.!?\n]+))?[.!?\n]*$", re.IGNORECASE)),
    ("past_like", re.compile(r"\bраньше\s+мне\s+нрав(?:ился|илась|ились)\s+(?P<value>[^.!?\n]+)", re.IGNORECASE)),
    ("past_prefer", re.compile(r"\bраньше\s+я\s+предпочитал(?:а)?\s+(?P<value>[^.!?\n]+)", re.IGNORECASE)),
)


HYPOTHETICAL_RE = re.compile(
    r"\b(?:might|may|could|would|if\s+i|maybe|perhaps|considering|thinking\s+about)\b",
    re.IGNORECASE,
)


def _preference_values(raw: str) -> list[str]:
    value = clean_value(raw)
    value = re.split(
        r"\s+(?:and|but)\s+(?:now\s+)?i\s+(?:now\s+)?(?:used\s+to\s+)?(?:prefer|like|love|dislike|do\s+not\s+like|don't\s+like)\b",
        value,
        maxsplit=1,
        flags=re.IGNORECASE,
    )[0]
    value = re.split(r"\s+because\s+", value, maxsplit=1, flags=re.IGNORECASE)[0]
    value = re.split(r"\s+when\s+", value, maxsplit=1, flags=re.IGNORECASE)[0]
    return [clean_value(part) for part in re.split(r",|\s+and\s+", value) if clean_value(part)]


def _classify_preference(value: str, match: re.Match[str]) -> tuple[str, str]:
    explicit_category = clean_value(match.groupdict().get("preference_category") or "").lower()
    if explicit_category:
        if explicit_category in {"drink", "snack", "meal", "food"}:
            return "food_drink", explicit_category
        return explicit_category, explicit_category
    normalized = value.lower()
    if re.search(r"\b(?:coffee|tea|espresso|matcha|water|wine|beer|juice)\b", normalized):
        return "food_drink", "drink"
    if re.search(r"\b(?:sushi|pizza|salad|pasta|gluten|snack|meal)\b", normalized):
        return "food_drink", "food"
    if re.search(r"\b(?:python|postgres|docker|kubernetes|terraform|tool|app)\b", normalized):
        return "work_tools", "tool"
    return "general", "general"


def _original_phrasing(match: re.Match[str]) -> str:
    return clean_value(match.group(0)).rstrip(".!?")


def extract(context: ExtractionContext) -> list[dict]:
    if HYPOTHETICAL_RE.search(context.text):
        return []
    evidence = build_evidence(context)
    candidates: list[dict] = []
    seen: set[tuple[str, str, bool]] = set()
    has_current_self_correction = bool(
        re.search(r"\bbut\s+now\s+i\s+(?:prefer|like|love)\b", context.text, re.IGNORECASE)
        or re.search(
            r"\bi\s+(?:currently\s+)?(?:prefer|like|love)\b.*\bbut\s+i\s+used\s+to\s+(?:prefer|like|love|dislike)\b",
            context.text,
            re.IGNORECASE,
        )
    )
    for verb, pattern in PREFERENCE_PATTERNS:
        for match in pattern.finditer(context.text):
            values = _preference_values(match.group("value"))
            if not values:
                continue
            review_reasons = review_reasons_for_context(context)
            action = "prefers" if verb == "prefer" else "likes"
            polarity = "like"
            strength = "medium"
            reason = ""
            is_current = True
            if verb == "dislike":
                action = "dislikes"
                polarity = "dislike"
                strength = "strong" if (match.groupdict().get("strongly") or "").strip() else "medium"
                reason = clean_value(match.groupdict().get("reason") or "")
            elif verb == "past_like":
                action = "used to like"
                is_current = False
            elif verb == "past_prefer":
                action = "used to prefer"
                is_current = False
            elif verb == "past_dislike":
                action = "used to dislike"
                polarity = "dislike"
                is_current = False
            for value in values:
                key = (value.lower(), polarity, is_current)
                if key in seen:
                    continue
                seen.add(key)
                preference_domain, preference_category = _classify_preference(value, match)
                context_note = clean_value(match.groupdict().get("context") or "")
                valid_to = "now" if (not is_current and (has_current_self_correction or verb.startswith("past_"))) else ""
                candidates.append(
                    {
                        "domain": "preferences",
                        "category": "preference",
                        "subcategory": "",
                        "canonical_key": f"{context.subject_key}:preferences:preference:{slugify(value)}",
                        "payload": {
                            "value": value,
                            "preference_domain": preference_domain,
                            "preference_category": preference_category,
                            "polarity": polarity,
                            "strength": strength,
                            "reason": reason,
                            "is_current": is_current,
                            "temporal_status": "current" if is_current else "past",
                            "valid_from": "",
                            "valid_to": valid_to,
                            "original_phrasing": _original_phrasing(match),
                            "context": context_note,
                        },
                        "summary": f"{context.subject_display} {action} {value}.",
                        "confidence": 0.85 if context.person_id is not None else 0.6,
                        "reason": ",".join(review_reasons),
                        "needs_review": bool(review_reasons),
                        "evidence": evidence,
                    }
                )
    return candidates

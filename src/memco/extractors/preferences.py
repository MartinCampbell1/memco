from __future__ import annotations

import re

from memco.extractors.base import ExtractionContext, build_evidence, clean_value, review_reasons_for_context
from memco.utils import slugify


PREFERENCE_PATTERNS = (
    ("dislike", re.compile(r"\bi\s+do\s+not\s+like\s+(?P<value>[^.!?\n]+?)(?:\s+because\s+(?P<reason>[^.!?\n]+))?(?=$|[.!?\n])", re.IGNORECASE)),
    ("dislike", re.compile(r"\bi\s+don't\s+like\s+(?P<value>[^.!?\n]+?)(?:\s+because\s+(?P<reason>[^.!?\n]+))?(?=$|[.!?\n])", re.IGNORECASE)),
    ("dislike", re.compile(r"\bi\s+(?P<strongly>strongly\s+)?dislike\s+(?P<value>[^.!?\n]+?)(?:\s+because\s+(?P<reason>[^.!?\n]+))?(?=$|[.!?\n])", re.IGNORECASE)),
    ("prefer", re.compile(r"\bi\s+prefer\s+(?P<value>[^.!?\n]+)", re.IGNORECASE)),
    ("like", re.compile(r"\bi\s+love\s+(?P<value>[^.!?\n]+)", re.IGNORECASE)),
    ("like", re.compile(r"\bi\s+like\s+(?P<value>[^.!?\n]+)", re.IGNORECASE)),
    ("like", re.compile(r"\b(?P<value>[A-Za-z][^.!?\n]+?)\s+is\s+my\s+go-to\s+(?:drink|snack|meal|food|tool)\b", re.IGNORECASE)),
    ("past_like", re.compile(r"\bi\s+used\s+to\s+like\s+(?P<value>[^.!?\n]+)", re.IGNORECASE)),
    ("past_prefer", re.compile(r"\bi\s+used\s+to\s+prefer\s+(?P<value>[^.!?\n]+)", re.IGNORECASE)),
    ("past_dislike", re.compile(r"\bi\s+used\s+to\s+dislike\s+(?P<value>[^.!?\n]+)", re.IGNORECASE)),
    ("prefer", re.compile(r"\bя\s+предпочитаю\s+(?P<value>[^.!?\n]+)", re.IGNORECASE)),
    ("like", re.compile(r"\bмне\s+нрав(?:ится|ят)\s+(?P<value>[^.!?\n]+)", re.IGNORECASE)),
    ("dislike", re.compile(r"\bя\s+(?P<strongly>очень\s+)?не\s+люблю\s+(?P<value>[^.!?\n]+?)(?:\s+потому\s+что\s+(?P<reason>[^.!?\n]+))?[.!?\n]*$", re.IGNORECASE)),
    ("past_like", re.compile(r"\bраньше\s+мне\s+нрав(?:ился|илась|ились)\s+(?P<value>[^.!?\n]+)", re.IGNORECASE)),
    ("past_prefer", re.compile(r"\bраньше\s+я\s+предпочитал(?:а)?\s+(?P<value>[^.!?\n]+)", re.IGNORECASE)),
)


def _preference_values(raw: str) -> list[str]:
    value = clean_value(raw)
    value = re.split(
        r"\s+(?:and|but)\s+i\s+(?:prefer|like|love|dislike|do\s+not\s+like|don't\s+like)\b",
        value,
        maxsplit=1,
        flags=re.IGNORECASE,
    )[0]
    value = re.split(r"\s+because\s+", value, maxsplit=1, flags=re.IGNORECASE)[0]
    return [clean_value(part) for part in re.split(r",|\s+and\s+", value) if clean_value(part)]


def extract(context: ExtractionContext) -> list[dict]:
    evidence = build_evidence(context)
    candidates: list[dict] = []
    seen: set[tuple[str, str, bool]] = set()
    has_current_self_correction = bool(
        re.search(r"\bbut\s+now\s+i\s+(?:prefer|like|love)\b", context.text, re.IGNORECASE)
    )
    for verb, pattern in PREFERENCE_PATTERNS:
        if has_current_self_correction and verb.startswith("past_"):
            continue
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
                candidates.append(
                    {
                        "domain": "preferences",
                        "category": "preference",
                        "subcategory": "",
                        "canonical_key": f"{context.subject_key}:preferences:preference:{slugify(value)}",
                        "payload": {
                            "value": value,
                            "polarity": polarity,
                            "strength": strength,
                            "reason": reason,
                            "is_current": is_current,
                        },
                        "summary": f"{context.subject_display} {action} {value}.",
                        "confidence": 0.85 if context.person_id is not None else 0.6,
                        "reason": ",".join(review_reasons),
                        "needs_review": bool(review_reasons),
                        "evidence": evidence,
                    }
                )
    return candidates

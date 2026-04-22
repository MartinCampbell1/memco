from __future__ import annotations

import re

from memco.extractors.base import ExtractionContext, build_evidence, clean_value, review_reasons_for_context
from memco.utils import slugify


PREFERENCE_PATTERNS = (
    ("prefer", re.compile(r"\bi\s+prefer\s+(?P<value>[^.!?\n]+)", re.IGNORECASE)),
    ("like", re.compile(r"\bi\s+like\s+(?P<value>[^.!?\n]+)", re.IGNORECASE)),
    ("dislike", re.compile(r"\bi\s+(?P<strongly>strongly\s+)?dislike\s+(?P<value>[^.!?\n]+?)(?:\s+because\s+(?P<reason>[^.!?\n]+))?[.!?\n]*$", re.IGNORECASE)),
    ("past_like", re.compile(r"\bi\s+used\s+to\s+like\s+(?P<value>[^.!?\n]+)", re.IGNORECASE)),
    ("past_prefer", re.compile(r"\bi\s+used\s+to\s+prefer\s+(?P<value>[^.!?\n]+)", re.IGNORECASE)),
    ("past_dislike", re.compile(r"\bi\s+used\s+to\s+dislike\s+(?P<value>[^.!?\n]+)", re.IGNORECASE)),
    ("prefer", re.compile(r"\bя\s+предпочитаю\s+(?P<value>[^.!?\n]+)", re.IGNORECASE)),
    ("like", re.compile(r"\bмне\s+нрав(?:ится|ят)\s+(?P<value>[^.!?\n]+)", re.IGNORECASE)),
    ("dislike", re.compile(r"\bя\s+(?P<strongly>очень\s+)?не\s+люблю\s+(?P<value>[^.!?\n]+?)(?:\s+потому\s+что\s+(?P<reason>[^.!?\n]+))?[.!?\n]*$", re.IGNORECASE)),
    ("past_like", re.compile(r"\bраньше\s+мне\s+нрав(?:ился|илась|ились)\s+(?P<value>[^.!?\n]+)", re.IGNORECASE)),
    ("past_prefer", re.compile(r"\bраньше\s+я\s+предпочитал(?:а)?\s+(?P<value>[^.!?\n]+)", re.IGNORECASE)),
)


def extract(context: ExtractionContext) -> list[dict]:
    evidence = build_evidence(context)
    for verb, pattern in PREFERENCE_PATTERNS:
        match = pattern.search(context.text)
        if not match:
            continue
        value = clean_value(match.group("value"))
        if not value:
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
        return [
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
        ]
    return []

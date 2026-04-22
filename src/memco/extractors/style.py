from __future__ import annotations

from memco.extractors.base import ExtractionContext, build_evidence, review_reasons_for_context


STYLE_MARKERS = {
    "humorous": ("haha", "lol", "joke", "funny"),
    "warm": ("thanks", "thank you", "glad", "appreciate"),
    "direct": ("please do", "just", "need", "must"),
}


def extract(context: ExtractionContext) -> list[dict]:
    lowered = context.text.lower()
    tone = "unknown"
    for candidate_tone, markers in STYLE_MARKERS.items():
        if any(marker in lowered for marker in markers):
            tone = candidate_tone
            break
    if tone == "unknown":
        return []
    review_reasons = review_reasons_for_context(context)
    return [
        {
            "domain": "style",
            "category": "communication_style",
            "subcategory": "",
            "canonical_key": f"{context.subject_key}:style:communication_style:{tone}",
            "payload": {
                "tone": tone,
                "verbosity": "medium",
                "emoji_usage": "none",
                "language_mix": [],
                "signature_phrases": [],
                "punctuation_style": None,
                "generation_guidance": f"Lean {tone} but do not use this as factual evidence.",
                "confidence": 0.6,
            },
            "summary": f"{context.subject_display} often communicates in a {tone} tone.",
            "confidence": 0.6,
            "reason": ",".join(review_reasons),
            "needs_review": bool(review_reasons),
            "evidence": build_evidence(context),
        }
    ]


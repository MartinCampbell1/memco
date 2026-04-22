from __future__ import annotations

import re
from dataclasses import dataclass

from memco.extractors.base import ExtractionContext, build_evidence, review_reasons_for_context


@dataclass(frozen=True)
class PsychometricRule:
    framework: str
    trait: str
    pattern: re.Pattern[str]
    direction: str


PSYCHOMETRIC_RULES = (
    PsychometricRule("big_five", "openness", re.compile(r"\bi(?:'m| am)\s+(?:very\s+)?curious\b", re.IGNORECASE), "high"),
    PsychometricRule("schwartz_values", "self_direction", re.compile(r"\bi\s+value\s+independence\b", re.IGNORECASE), "high"),
    PsychometricRule("panas", "positive_affect", re.compile(r"\bi\s+feel\s+excited\b", re.IGNORECASE), "high"),
    PsychometricRule("via", "kindness", re.compile(r"\bi\s+try\s+to\s+be\s+kind\b", re.IGNORECASE), "high"),
    PsychometricRule("iri", "empathic_concern", re.compile(r"\bi\s+easily\s+feel\s+what\s+others\s+feel\b", re.IGNORECASE), "high"),
    PsychometricRule("moral_foundations", "care", re.compile(r"\bi\s+believe\s+caring\s+for\s+others\s+matters\b", re.IGNORECASE), "high"),
    PsychometricRule("political_compass", "libertarian", re.compile(r"\bi\s+favor\s+limited\s+government\b", re.IGNORECASE), "high"),
    PsychometricRule("kohlberg", "conventional_reasoning", re.compile(r"\bi\s+follow\s+rules\s+because\s+they\s+keep\s+society\s+working\b", re.IGNORECASE), "high"),
    PsychometricRule("cognitive_ability_profile", "analytical_reasoning", re.compile(r"\bi\s+solve\s+complex\s+logic\s+puzzles\s+quickly\b", re.IGNORECASE), "high"),
)

COUNTEREVIDENCE_MARKERS = (
    re.compile(r"\bbut\s+sometimes\s+(?P<quote>[^.!?\n]+)", re.IGNORECASE),
    re.compile(r"\bhowever[, ]+\s*(?P<quote>[^.!?\n]+)", re.IGNORECASE),
)


def extract(context: ExtractionContext) -> list[dict]:
    evidence = build_evidence(context)
    counterevidence_quotes: list[dict] = []
    for counter_pattern in COUNTEREVIDENCE_MARKERS:
        match = counter_pattern.search(context.text)
        if not match:
            continue
        counterevidence_quotes.append(
            {
                "quote": match.group("quote").strip(),
                "message_ids": [str(context.message_id)] if context.message_id is not None else [],
                "interpretation": "Possible counter-signal in the same snippet.",
            }
        )
        break

    candidates: list[dict] = []
    for rule in PSYCHOMETRIC_RULES:
        if not rule.pattern.search(context.text):
            continue
        review_reasons = review_reasons_for_context(context)
        base_confidence = 0.55 if context.person_id is not None else 0.4
        counterevidence_penalty = 0.12 if counterevidence_quotes else 0.0
        trait_confidence = max(0.2, round(base_confidence - counterevidence_penalty, 2))
        candidates.append(
            {
                "domain": "psychometrics",
                "category": "trait",
                "subcategory": rule.framework,
                "canonical_key": f"{context.subject_key}:psychometrics:{rule.framework}:{rule.trait}",
                "payload": {
                    "framework": rule.framework,
                    "trait": rule.trait,
                    "score": 0.7,
                    "score_scale": "0_1",
                    "direction": rule.direction,
                    "confidence": trait_confidence,
                    "evidence_quotes": [
                        {
                            "quote": context.text.strip(),
                            "message_ids": [str(context.message_id)] if context.message_id is not None else [],
                            "interpretation": f"Possible signal for {rule.trait}.",
                        }
                    ],
                    "counterevidence_quotes": list(counterevidence_quotes),
                    "conservative_update": True,
                    "last_updated": context.occurred_at or "",
                    "use_in_generation": trait_confidence >= 0.5,
                    "safety_notes": "Non-diagnostic psychometric hint; do not use as factual evidence.",
                },
                "summary": f"{context.subject_display} may show {rule.trait} ({rule.framework}).",
                "confidence": trait_confidence,
                "reason": ",".join(review_reasons),
                "needs_review": bool(review_reasons),
                "evidence": evidence,
            }
        )
    return candidates

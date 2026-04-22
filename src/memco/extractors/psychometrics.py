from __future__ import annotations

import re
from dataclasses import dataclass
from collections import defaultdict

from memco.extractors.base import ExtractionContext, build_evidence, review_reasons_for_context


@dataclass(frozen=True)
class PsychometricRule:
    framework: str
    trait: str
    pattern: re.Pattern[str]
    direction: str
    signal_kind: str
    base_confidence: float


@dataclass(frozen=True)
class PsychometricSignal:
    framework: str
    trait: str
    direction: str
    signal_kind: str
    explicit_self_description: bool
    signal_confidence: float
    evidence_quote: dict
    observed_at: str


PSYCHOMETRIC_RULES = (
    PsychometricRule("big_five", "openness", re.compile(r"\bi(?:'m| am)\s+(?:very\s+)?curious\b", re.IGNORECASE), "high", "explicit_self_description", 0.72),
    PsychometricRule("schwartz_values", "self_direction", re.compile(r"\bi\s+value\s+independence\b", re.IGNORECASE), "high", "explicit_self_description", 0.71),
    PsychometricRule("panas", "positive_affect", re.compile(r"\bi\s+feel\s+excited\b", re.IGNORECASE), "high", "behavioral_hint", 0.52),
    PsychometricRule("via", "kindness", re.compile(r"\bi\s+try\s+to\s+be\s+kind\b", re.IGNORECASE), "high", "behavioral_hint", 0.58),
    PsychometricRule("via", "kindness", re.compile(r"\bi\s+help\s+people\s+when\s+they\s+struggle\b", re.IGNORECASE), "high", "behavioral_hint", 0.61),
    PsychometricRule("iri", "empathic_concern", re.compile(r"\bi\s+easily\s+feel\s+what\s+others\s+feel\b", re.IGNORECASE), "high", "behavioral_hint", 0.58),
    PsychometricRule("moral_foundations", "care", re.compile(r"\bi\s+believe\s+caring\s+for\s+others\s+matters\b", re.IGNORECASE), "high", "explicit_self_description", 0.66),
    PsychometricRule("political_compass", "libertarian", re.compile(r"\bi\s+favor\s+limited\s+government\b", re.IGNORECASE), "high", "explicit_self_description", 0.66),
    PsychometricRule("kohlberg", "conventional_reasoning", re.compile(r"\bi\s+follow\s+rules\s+because\s+they\s+keep\s+society\s+working\b", re.IGNORECASE), "high", "behavioral_hint", 0.56),
    PsychometricRule("cognitive_ability_profile", "analytical_reasoning", re.compile(r"\bi\s+solve\s+complex\s+logic\s+puzzles\s+quickly\b", re.IGNORECASE), "high", "behavioral_hint", 0.57),
)

COUNTEREVIDENCE_MARKERS = (
    re.compile(r"\bbut\s+sometimes\s+(?P<quote>[^.!?\n]+)", re.IGNORECASE),
    re.compile(r"\bhowever[, ]+\s*(?P<quote>[^.!?\n]+)", re.IGNORECASE),
)

FRAMEWORK_GENERATION_THRESHOLDS = {
    "big_five": 0.7,
    "schwartz_values": 0.7,
    "panas": 0.75,
    "via": 0.68,
    "iri": 0.72,
    "moral_foundations": 0.7,
    "political_compass": 0.7,
    "kohlberg": 0.74,
    "cognitive_ability_profile": 0.74,
}


def _framework_threshold(framework: str) -> float:
    return FRAMEWORK_GENERATION_THRESHOLDS.get(framework, 0.72)


def _build_counterevidence(context: ExtractionContext) -> list[dict]:
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
    return counterevidence_quotes


def extract_signals(context: ExtractionContext) -> list[PsychometricSignal]:
    signals: list[PsychometricSignal] = []
    for rule in PSYCHOMETRIC_RULES:
        if not rule.pattern.search(context.text):
            continue
        explicit_self_description = rule.signal_kind == "explicit_self_description"
        signal_confidence = (
            rule.base_confidence
            if context.person_id is not None
            else max(0.2, round(rule.base_confidence - 0.12, 2))
        )
        signals.append(
            PsychometricSignal(
                framework=rule.framework,
                trait=rule.trait,
                direction=rule.direction,
                signal_kind=rule.signal_kind,
                explicit_self_description=explicit_self_description,
                signal_confidence=signal_confidence,
                evidence_quote={
                    "quote": context.text.strip(),
                    "message_ids": [str(context.message_id)] if context.message_id is not None else [],
                    "interpretation": f"Possible signal for {rule.trait}.",
                },
                observed_at=context.occurred_at or "",
            )
        )
    return signals


def score_signal_groups(*, signals: list[PsychometricSignal], counterevidence_quotes: list[dict]) -> list[dict]:
    grouped: dict[tuple[str, str], list[PsychometricSignal]] = defaultdict(list)
    for signal in signals:
        grouped[(signal.framework, signal.trait)].append(signal)

    profiles: list[dict] = []
    for (framework, trait), items in grouped.items():
        evidence_quotes = [item.evidence_quote for item in items]
        evidence_count = len(evidence_quotes)
        explicit_self_description = any(item.explicit_self_description for item in items)
        avg_signal_confidence = round(sum(item.signal_confidence for item in items) / evidence_count, 2)
        evidence_bonus = 0.09 * max(0, evidence_count - 1)
        counterevidence_penalty = 0.18 * len(counterevidence_quotes)
        scored_confidence = max(0.2, min(0.95, round(avg_signal_confidence + evidence_bonus - counterevidence_penalty, 2)))
        score = max(0.2, min(0.95, round(scored_confidence + 0.05 * max(0, evidence_count - 1), 2)))
        threshold = _framework_threshold(framework)
        use_in_generation = (
            (evidence_count >= 2 or explicit_self_description)
            and not counterevidence_quotes
            and scored_confidence >= threshold
        )
        signal_kinds = sorted({item.signal_kind for item in items})
        extracted_signal = {
            "signal_kind": signal_kinds[0] if len(signal_kinds) == 1 else "mixed_signal",
            "explicit_self_description": explicit_self_description,
            "signal_confidence": avg_signal_confidence,
            "evidence_count": evidence_count,
            "counterevidence_count": len(counterevidence_quotes),
            "evidence_quotes": evidence_quotes,
            "counterevidence_quotes": list(counterevidence_quotes),
            "observed_at": max((item.observed_at for item in items), default=""),
        }
        scored_profile = {
            "score": score,
            "score_scale": "0_1",
            "direction": items[0].direction,
            "confidence": scored_confidence,
            "framework_threshold": threshold,
            "conservative_update": True,
            "use_in_generation": use_in_generation,
        }
        profiles.append(
            {
                "framework": framework,
                "trait": trait,
                "direction": items[0].direction,
                "confidence": scored_confidence,
                "extracted_signal": extracted_signal,
                "scored_profile": scored_profile,
                "evidence_quotes": evidence_quotes,
                "counterevidence_quotes": list(counterevidence_quotes),
            }
        )
    return profiles


def _build_signal_payload(*, profile: dict) -> tuple[dict, dict]:
    extracted_signal = profile["extracted_signal"]
    extracted_signal = {
        "signal_kind": extracted_signal["signal_kind"],
        "explicit_self_description": extracted_signal["explicit_self_description"],
        "signal_confidence": extracted_signal["signal_confidence"],
        "evidence_count": extracted_signal["evidence_count"],
        "counterevidence_count": extracted_signal["counterevidence_count"],
        "evidence_quotes": list(extracted_signal["evidence_quotes"]),
        "counterevidence_quotes": list(extracted_signal["counterevidence_quotes"]),
        "observed_at": extracted_signal["observed_at"],
    }
    scored_profile = dict(profile["scored_profile"])
    return extracted_signal, scored_profile


def extract(context: ExtractionContext) -> list[dict]:
    evidence = build_evidence(context)
    counterevidence_quotes = _build_counterevidence(context)
    signals = extract_signals(context)
    profiles = score_signal_groups(signals=signals, counterevidence_quotes=counterevidence_quotes)

    candidates: list[dict] = []
    for profile in profiles:
        review_reasons = review_reasons_for_context(context)
        extracted_signal, scored_profile = _build_signal_payload(
            profile=profile,
        )
        trait_confidence = scored_profile["confidence"]
        candidates.append(
            {
                "domain": "psychometrics",
                "category": "trait",
                "subcategory": profile["framework"],
                "canonical_key": f"{context.subject_key}:psychometrics:{profile['framework']}:{profile['trait']}",
                "payload": {
                    "framework": profile["framework"],
                    "trait": profile["trait"],
                    "extracted_signal": extracted_signal,
                    "scored_profile": scored_profile,
                    "score": scored_profile["score"],
                    "score_scale": scored_profile["score_scale"],
                    "direction": scored_profile["direction"],
                    "confidence": trait_confidence,
                    "evidence_quotes": list(extracted_signal["evidence_quotes"]),
                    "counterevidence_quotes": list(extracted_signal["counterevidence_quotes"]),
                    "conservative_update": scored_profile["conservative_update"],
                    "last_updated": context.occurred_at or "",
                    "use_in_generation": scored_profile["use_in_generation"],
                    "safety_notes": "Non-diagnostic psychometric hint; do not use as factual evidence.",
                },
                "summary": f"{context.subject_display} may show {profile['trait']} ({profile['framework']}).",
                "confidence": trait_confidence,
                "reason": ",".join(review_reasons),
                "needs_review": bool(review_reasons),
                "evidence": evidence,
            }
        )
    return candidates

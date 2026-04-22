from __future__ import annotations

from memco.consolidation.base import ConsolidationPolicy
from memco.consolidation.biography import BiographyConsolidationPolicy
from memco.consolidation.experiences import ExperiencesConsolidationPolicy
from memco.consolidation.preferences import PreferencesConsolidationPolicy
from memco.consolidation.social_circle import SocialCircleConsolidationPolicy
from memco.consolidation.work import WorkConsolidationPolicy


_POLICIES: dict[str, ConsolidationPolicy] = {
    "biography": BiographyConsolidationPolicy(),
    "preferences": PreferencesConsolidationPolicy(),
    "social_circle": SocialCircleConsolidationPolicy(),
    "work": WorkConsolidationPolicy(),
    "experiences": ExperiencesConsolidationPolicy(),
}


def get_policy(domain: str) -> ConsolidationPolicy:
    return _POLICIES.get(domain, ConsolidationPolicy())


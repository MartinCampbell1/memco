from __future__ import annotations

from . import biography, experiences, preferences, psychometrics, social_circle, style, work
from .base import ExtractionContext, validate_candidate


class ExtractionOrchestrator:
    def extract(
        self,
        context: ExtractionContext,
        *,
        include_style: bool = False,
        include_psychometrics: bool = False,
    ) -> list[dict]:
        candidates: list[dict] = []
        for module in (biography, preferences, social_circle, work, experiences):
            candidates.extend(validate_candidate(candidate) for candidate in module.extract(context))
        if include_psychometrics:
            candidates.extend(validate_candidate(candidate) for candidate in psychometrics.extract(context))
        if include_style:
            candidates.extend(validate_candidate(candidate) for candidate in style.extract(context))
        return candidates

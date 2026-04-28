from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from memco.extractors.base import (
    EXTRACTION_SCHEMA_NAME,
    ExtractionContext,
    build_extraction_system_prompt,
    build_prompt_payload,
)


@dataclass(frozen=True)
class StructuredExtractionPrompt:
    schema_name: str
    system_prompt: str
    payload: dict[str, Any]


def build_structured_extraction_prompt(
    context: ExtractionContext,
    *,
    include_style: bool = False,
    include_psychometrics: bool = False,
    domain_names: tuple[str, ...] | None = None,
) -> StructuredExtractionPrompt:
    return StructuredExtractionPrompt(
        schema_name=EXTRACTION_SCHEMA_NAME,
        system_prompt=build_extraction_system_prompt(
            include_style=include_style,
            include_psychometrics=include_psychometrics,
            domain_names=domain_names,
        ),
        payload=build_prompt_payload(
            context,
            include_style=include_style,
            include_psychometrics=include_psychometrics,
            domain_names=domain_names,
        ),
    )


__all__ = ["StructuredExtractionPrompt", "build_structured_extraction_prompt"]

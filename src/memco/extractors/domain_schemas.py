from __future__ import annotations

from typing import Any

from memco.extractors.base import (
    DOMAIN_PROMPT_CONTRACTS,
    EXTRACTION_CONTRACT_VERSION,
    DomainPromptContract,
    build_extraction_contract,
)


CANONICAL_LLM_DOMAINS: tuple[str, ...] = (
    "biography",
    "experiences",
    "preferences",
    "social_circle",
    "work",
    "psychometrics",
)


def get_domain_contract(domain: str) -> DomainPromptContract:
    try:
        return DOMAIN_PROMPT_CONTRACTS[domain]
    except KeyError as exc:
        raise ValueError(f"Unknown extraction domain: {domain}") from exc


def build_domain_schema(
    *,
    include_style: bool = False,
    include_psychometrics: bool = False,
    domain_names: tuple[str, ...] | None = None,
) -> dict[str, Any]:
    return build_extraction_contract(
        include_style=include_style,
        include_psychometrics=include_psychometrics,
        domain_names=domain_names,
    )


__all__ = [
    "CANONICAL_LLM_DOMAINS",
    "DOMAIN_PROMPT_CONTRACTS",
    "EXTRACTION_CONTRACT_VERSION",
    "DomainPromptContract",
    "build_domain_schema",
    "get_domain_contract",
]

from __future__ import annotations

CANONICAL_RELATION_TYPES = (
    "sister",
    "brother",
    "mother",
    "father",
    "partner",
    "spouse",
    "friend",
    "colleague",
    "son",
    "daughter",
    "boss",
    "manager",
    "roommate",
    "neighbor",
)

RELATION_TYPE_ALIASES = {
    "mom": "mother",
    "mum": "mother",
    "dad": "father",
    "wife": "spouse",
    "husband": "spouse",
    "сестра": "sister",
    "сестрой": "sister",
    "брат": "brother",
    "братом": "brother",
    "мама": "mother",
    "мать": "mother",
    "папа": "father",
    "отец": "father",
    "жена": "spouse",
    "муж": "spouse",
    "партнер": "partner",
    "партнером": "partner",
    "друг": "friend",
    "другом": "friend",
    "коллега": "colleague",
    "коллегой": "colleague",
}

RELATION_QUERY_TERMS = tuple(sorted(set(CANONICAL_RELATION_TYPES) | set(RELATION_TYPE_ALIASES)))
FAMILY_SOCIAL_BRIDGE_RELATION_TYPES = frozenset(
    {"sister", "brother", "mother", "father", "partner", "spouse", "friend", "colleague"}
)


def canonical_relation_type(value: str) -> str:
    normalized = " ".join((value or "").strip().lower().replace("-", " ").split())
    return RELATION_TYPE_ALIASES.get(normalized, normalized)

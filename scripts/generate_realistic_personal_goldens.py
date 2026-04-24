from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "eval" / "personal_memory_goldens" / "realistic_personal_memory_goldens.jsonl"
NOW = "2026-04-24T00:00:00Z"

FIRST_NAMES = [
    "Maya",
    "Jonas",
    "Leila",
    "Noah",
    "Priya",
    "Owen",
    "Clara",
    "Mateo",
    "Sofia",
    "Iris",
    "Nadia",
    "Elias",
    "Amara",
    "Victor",
    "Helena",
    "Rafael",
    "Anika",
    "Theo",
    "Selin",
    "David",
]
LAST_NAMES = [
    "Rivera",
    "Morgan",
    "Patel",
    "Brooks",
    "Shah",
    "Kim",
    "Stone",
    "Costa",
    "Nguyen",
    "Ivanov",
    "Marin",
    "Okafor",
    "Hughes",
    "Silva",
    "Kowalski",
]
CITIES = ["Lisbon", "Porto", "Coimbra", "Madrid", "Berlin", "Prague", "Tallinn", "Valencia", "Paris", "Vienna"]
TOOLS = ["Python", "Postgres", "Figma", "Linear", "Notion", "Metabase", "Retool", "dbt", "Looker", "TypeScript"]
PROJECTS = [
    "Project Phoenix",
    "Atlas migration",
    "Care dashboard",
    "Billing cleanup",
    "Hermes importer",
    "Launch calendar",
    "Kite onboarding",
    "Northstar notes",
]
PREFERENCES = [
    "coffee now after previously preferring tea",
    "window seats on morning flights",
    "quiet hotels near transit",
    "black notebooks for planning",
    "early calls before lunch",
    "vegetarian ramen",
    "paper boarding passes",
    "dark roast coffee",
    "standing desks",
    "noise cancelling headphones",
]
EVENTS = [
    "October 2023 serious accident",
    "Lisbon design retreat",
    "PyCon mentoring day",
    "founder dinner",
    "migration review",
    "customer interview sprint",
    "winter residency",
    "portfolio workshop",
    "security tabletop",
    "product offsite",
]
RELATIONS = [
    ("sister", "Maria in Porto"),
    ("friend", "Owen Park"),
    ("mother", "Elena Rivera"),
    ("partner", "Noah Kim"),
    ("colleague", "Priya Shah"),
]
HYPOTHETICAL_QUERIES = [
    ("Does Maya Rivera like sushi?", "preferences", "preference", "sushi"),
    ("Does Jonas Morgan live in Paris?", "biography", "residence", "Paris"),
    ("Does Leila Patel own a red Vespa?", "biography", "vehicle", "red Vespa"),
    ("Does Noah Brooks prefer midnight calls?", "preferences", "preference", "midnight calls"),
    ("Does Priya Shah have a villa in Cannes?", "biography", "residence", "villa in Cannes"),
]


def person(prefix: str, index: int) -> tuple[str, str]:
    first = FIRST_NAMES[(index - 1) % len(FIRST_NAMES)]
    last = LAST_NAMES[((index - 1) * 3 + len(prefix)) % len(LAST_NAMES)]
    return f"realistic-{prefix}-{index:03d}", f"{first} {last}"


def fact(
    *,
    slug: str,
    name: str,
    key: str,
    domain: str,
    category: str,
    payload: dict,
    summary: str,
    status: str = "active",
    event_at: str = "",
    valid_from: str = "",
) -> dict:
    return {
        "canonical_key": f"{slug}:{key}",
        "category": category,
        "domain": domain,
        "event_at": event_at,
        "observed_at": NOW,
        "payload": payload,
        "person_display_name": name,
        "person_slug": slug,
        "quote_text": summary,
        "status": status,
        "summary": summary,
        "valid_from": valid_from,
    }


def make_case(
    *,
    case_id: str,
    scenario: str,
    group: str,
    slug: str,
    name: str,
    query: str,
    domain: str,
    category: str,
    support: str,
    expected: list[str] | None = None,
    forbidden: list[str] | None = None,
    facts: list[dict] | None = None,
    refused: bool = False,
    temporal_mode: str = "auto",
    evidence_min: int = 1,
    limit: int = 1,
    source_text: str = "",
    source_check: str = "",
) -> dict:
    item = {
        "id": case_id,
        "scenario": scenario,
        "group": group,
        "person_slug": slug,
        "person_display_name": name,
        "query": query,
        "domain": domain,
        "domain_category": category,
        "expect_refused": refused,
        "expected_support_level": support,
        "expected_values": expected or [],
        "forbidden_values": forbidden or [],
        "seed_facts": facts or [],
        "temporal_mode": temporal_mode,
        "expected_evidence_count_min": evidence_min,
        "limit": limit,
    }
    if source_text:
        item["source_text"] = source_text
    if source_check:
        item["source_hard_check"] = source_check
    return item


def build_cases() -> list[dict]:
    cases: list[dict] = []

    for i in range(1, 26):
        slug, name = person("biography", i)
        value = [
            "stores recovery codes in the family 1Password vault",
            "keeps the passport in a blue travel pouch",
            "uses the downstairs office for late client calls",
            "keeps project receipts in the annual tax folder",
            "stores bike keys in the kitchen drawer",
        ][(i - 1) % 5]
        cases.append(
            make_case(
                case_id=f"realistic_biography_{i:03d}",
                scenario="biography",
                group="core_fact",
                slug=slug,
                name=name,
                query=f"What private note is recorded for {name}?",
                domain="biography",
                category="other_stable_self_knowledge",
                support="supported",
                expected=[value],
                facts=[
                    fact(
                        slug=slug,
                        name=name,
                        key="biography/private-note",
                        domain="biography",
                        category="other_stable_self_knowledge",
                        payload={"fact": value},
                        summary=f"{name} {value}.",
                    )
                ],
            )
        )

    for i in range(1, 26):
        slug, name = person("work", i)
        if i == 1:
            cases.append(
                make_case(
                    case_id=f"realistic_work_{i:03d}",
                    scenario="work",
                    group="core_fact",
                    slug=slug,
                    name=name,
                    query=f"What tools does {name} use?",
                    domain="work",
                    category="tool",
                    support="supported",
                    expected=["Python", "Postgres"],
                    forbidden=["Ruby"],
                    facts=[
                        fact(
                            slug=slug,
                            name=name,
                            key="work/tool/python",
                            domain="work",
                            category="tool",
                            payload={"tool": "Python"},
                            summary=f"{name} uses Python.",
                        ),
                        fact(
                            slug=slug,
                            name=name,
                            key="work/tool/postgres",
                            domain="work",
                            category="tool",
                            payload={"tool": "Postgres"},
                            summary=f"{name} uses Postgres.",
                        ),
                    ],
                    limit=3,
                    source_text="I use Python and Postgres.",
                    source_check="combined_tools_split",
                )
            )
            continue
        elif i == 2:
            category = "project"
            value = "Project Phoenix"
            summary = f"{name} worked on Project Phoenix and launched it in March."
            query = f"What project did {name} launch?"
            expected = [value, "March"]
            source_text = "I worked on Project Phoenix and launched it in March."
            source_check = "combined_project_temporal"
        else:
            category = "tool" if i % 2 else "project"
            value = TOOLS[i % len(TOOLS)] if category == "tool" else PROJECTS[i % len(PROJECTS)]
            summary = f"{name} uses {value}." if category == "tool" else f"{name} shipped {value}."
            query = f"What {category} is recorded for {name}?"
            expected = [value]
            source_text = ""
            source_check = ""
        cases.append(
            make_case(
                case_id=f"realistic_work_{i:03d}",
                scenario="work",
                group="core_fact",
                slug=slug,
                name=name,
                query=query,
                domain="work",
                category=category,
                support="supported",
                expected=expected,
                facts=[
                    fact(
                        slug=slug,
                        name=name,
                        key=f"work/{category}",
                        domain="work",
                        category=category,
                        payload={category: value, "temporal_anchor": "March"} if i == 2 else {category: value},
                        summary=summary,
                        event_at="March" if i == 2 else "",
                    )
                ],
                source_text=source_text,
                source_check=source_check,
            )
        )

    for i in range(1, 26):
        slug, name = person("experiences", i)
        event = EVENTS[(i - 1) % len(EVENTS)]
        event_at = "2023-10-01" if i == 1 else f"2025-{((i - 1) % 12) + 1:02d}-15"
        query = f"When did {name} have the October 2023 serious accident?" if i == 1 else f"What event did {name} attend?"
        source_text = "In October 2023 I had a serious accident at the Grand Canyon." if i == 1 else ""
        cases.append(
            make_case(
                case_id=f"realistic_experiences_{i:03d}",
                scenario="experiences",
                group="temporal" if i == 1 else "core_fact",
                slug=slug,
                name=name,
                query=query,
                domain="experiences",
                category="event",
                support="supported",
                expected=["2023" if i == 1 else event],
                temporal_mode="when" if i == 1 else "auto",
                source_text=source_text,
                source_check="experience_accident_temporal" if i == 1 else "",
                facts=[
                    fact(
                        slug=slug,
                        name=name,
                        key="experience/event",
                        domain="experiences",
                        category="event",
                        payload={"event": event, "event_at": event_at, "location": "Grand Canyon" if i == 1 else ""},
                        summary=(
                            f"{name} had a serious accident at the Grand Canyon in October 2023."
                            if i == 1
                            else f"{name} attended {event} on {event_at}."
                        ),
                        event_at=event_at,
                    )
                ],
            )
        )

    for i in range(1, 26):
        slug, name = person("preferences", i)
        value = PREFERENCES[(i - 1) % len(PREFERENCES)]
        if i == 1:
            cases.append(
                make_case(
                    case_id=f"realistic_preference_{i:03d}",
                    scenario="preferences",
                    group="preference",
                    slug=slug,
                    name=name,
                    query=f"What does {name} prefer now?",
                    domain="preferences",
                    category="preference",
                    support="supported",
                    expected=["coffee"],
                    temporal_mode="current",
                    facts=[
                        fact(
                            slug=slug,
                            name=name,
                            key="preference/old-tea",
                            domain="preferences",
                            category="preference",
                            payload={"value": "tea", "is_current": False},
                            summary=f"{name} used to prefer tea.",
                            status="deleted",
                        ),
                        fact(
                            slug=slug,
                            name=name,
                            key="preference/current-coffee",
                            domain="preferences",
                            category="preference",
                            payload={"value": "coffee", "is_current": True},
                            summary=f"{name} prefers coffee now after previously preferring tea.",
                        ),
                    ],
                    source_text="I prefer coffee, but I used to prefer tea.",
                    source_check="preference_update_current",
                )
            )
            continue
        cases.append(
            make_case(
                case_id=f"realistic_preference_{i:03d}",
                scenario="preferences",
                group="preference",
                slug=slug,
                name=name,
                query=f"What preference is recorded for {name}?",
                domain="preferences",
                category="preference",
                support="supported",
                expected=[value],
                facts=[
                    fact(
                        slug=slug,
                        name=name,
                        key="preference/current",
                        domain="preferences",
                        category="preference",
                        payload={"value": value},
                        summary=f"{name} prefers {value}.",
                    )
                ],
            )
        )

    for i in range(1, 26):
        slug, name = person("social", i)
        relation, target = RELATIONS[(i - 1) % len(RELATIONS)]
        cases.append(
            make_case(
                case_id=f"realistic_social_{i:03d}",
                scenario="social",
                group="social_family",
                slug=slug,
                name=name,
                query=f"Who is {name}'s {relation}?",
                domain="social_circle",
                category=relation,
                support="supported",
                expected=[target],
                facts=[
                    fact(
                        slug=slug,
                        name=name,
                        key=f"social/{relation}",
                        domain="social_circle",
                        category=relation,
                        payload={"relation": relation, "target_label": target},
                        summary=f"{name}'s {relation} is {target}.",
                    )
                ],
            )
        )

    for i in range(1, 26):
        slug, name = person("temporal", i)
        event = EVENTS[i % len(EVENTS)]
        event_at = f"2024-{((i - 1) % 12) + 1:02d}-01"
        cases.append(
            make_case(
                case_id=f"realistic_temporal_{i:03d}",
                scenario="temporal",
                group="temporal",
                slug=slug,
                name=name,
                query=f"When did {name} attend {event}?",
                domain="experiences",
                category="event",
                support="supported",
                expected=[event_at],
                temporal_mode="when",
                facts=[
                    fact(
                        slug=slug,
                        name=name,
                        key="temporal/event",
                        domain="experiences",
                        category="event",
                        payload={"event": event, "event_at": event_at},
                        summary=f"{name} attended {event}.",
                        event_at=event_at,
                    )
                ],
            )
        )

    for i in range(1, 51):
        slug, name = person("adversarial", i)
        true_city = CITIES[i % 4]
        false_city = CITIES[4 + (i % 6)]
        cases.append(
            make_case(
                case_id=f"realistic_adversarial_{i:03d}",
                scenario="adversarial",
                group="adversarial_false_premise",
                slug=slug,
                name=name,
                query=f"Does {name} live in {false_city}?",
                domain="biography",
                category="residence",
                support="contradicted",
                forbidden=[false_city],
                refused=True,
                evidence_min=0,
                facts=[
                    fact(
                        slug=slug,
                        name=name,
                        key="residence/current",
                        domain="biography",
                        category="residence",
                        payload={"city": true_city},
                        summary=f"{name} lives in {true_city}.",
                    )
                ],
            )
        )

    for i in range(1, 26):
        alice_slug, alice_name = person("cross-alice", i)
        bob_slug, bob_name = person("cross-bob", i)
        alice_city = "Lisbon"
        bob_city = "Berlin" if i == 1 else CITIES[4 + (i % 6)]
        bob_summary = "Bob in Berlin lives in Berlin." if i == 1 else f"{bob_name} lives in {bob_city}."
        cases.append(
            make_case(
                case_id=f"realistic_cross_person_{i:03d}",
                scenario="cross_person",
                group="cross_person_contamination",
                slug=alice_slug,
                name=alice_name,
                query=f"Where does {alice_name} live?",
                domain="biography",
                category="residence",
                support="supported",
                expected=[alice_city],
                forbidden=[bob_city],
                facts=[
                    fact(
                        slug=alice_slug,
                        name=alice_name,
                        key="residence/current",
                        domain="biography",
                        category="residence",
                        payload={"city": alice_city},
                        summary=f"{alice_name} lives in {alice_city}.",
                    ),
                    fact(
                        slug=bob_slug,
                        name=bob_name,
                        key="residence/current",
                        domain="biography",
                        category="residence",
                        payload={"city": bob_city},
                        summary=bob_summary,
                    ),
                ],
            )
        )

    for i in range(1, 26):
        slug, name = person("update", i)
        old_city = "Berlin" if i == 1 else CITIES[(i + 2) % len(CITIES)]
        current_city = "Lisbon" if i == 1 else CITIES[(i + 6) % len(CITIES)]
        cases.append(
            make_case(
                case_id=f"realistic_update_{i:03d}",
                scenario="update_supersede",
                group="rollback_update",
                slug=slug,
                name=name,
                query=f"Where does {name} live now?",
                domain="biography",
                category="residence",
                support="supported",
                expected=[current_city],
                forbidden=[old_city],
                temporal_mode="current",
                facts=[
                    fact(
                        slug=slug,
                        name=name,
                        key="residence/old",
                        domain="biography",
                        category="residence",
                        payload={"city": old_city},
                        summary=f"{name} lived in {old_city}.",
                        status="deleted",
                    ),
                    fact(
                        slug=slug,
                        name=name,
                        key="residence/current",
                        domain="biography",
                        category="residence",
                        payload={"city": current_city},
                        summary=f"{name} lives in {current_city}.",
                    ),
                ],
            )
        )

    for i in range(1, 26):
        slug, name = person("speakerless", i)
        value = [
            "renew passport before the May trip",
            "call the clinic before noon",
            "bring the blue notebook to Lisbon",
            "renew the coworking pass next month",
            "save the tax receipt after payment",
        ][(i - 1) % 5]
        cases.append(
            make_case(
                case_id=f"realistic_speakerless_{i:03d}",
                scenario="speakerless",
                group="speakerless_note",
                slug=slug,
                name=name,
                query=f"What did the speakerless note say about {name}?",
                domain="biography",
                category="other_stable_self_knowledge",
                support="supported",
                expected=[value],
                facts=[
                    fact(
                        slug=slug,
                        name=name,
                        key="speakerless/owner-note",
                        domain="biography",
                        category="other_stable_self_knowledge",
                        payload={"attribution_method": "owner_first_person_fallback", "fact": value},
                        summary=f"{name} speakerless note says {value}.",
                    )
                ],
            )
        )

    for i in range(1, 26):
        slug, name = person("negation", i)
        if i == 1:
            query, domain, category, forbidden = "Does Maya Rivera like sushi?", "preferences", "preference", "sushi"
            source_text = "I do not like sushi."
            source_check = "negated_preference_not_positive"
        elif i == 2:
            query, domain, category, forbidden = "Does Jonas Morgan live in Paris?", "biography", "residence", "Paris"
            source_text = "I might move to Paris next year."
            source_check = "hypothetical_residence_not_positive"
        elif i <= len(HYPOTHETICAL_QUERIES):
            query, domain, category, forbidden = HYPOTHETICAL_QUERIES[i - 1]
            source_text = ""
            source_check = ""
        else:
            domain = "biography" if i % 2 else "preferences"
            category = "residence" if domain == "biography" else "preference"
            forbidden = ["a house in Paris", "midnight calls", "a red Vespa", "sushi dinners"][i % 4]
            query = f"Does {name} have {forbidden}?"
            source_text = ""
            source_check = ""
        cases.append(
            make_case(
                case_id=f"realistic_negation_hypothetical_{i:03d}",
                scenario="negation_hypothetical",
                group="adversarial_false_premise",
                slug=slug,
                name=name,
                query=query,
                domain=domain,
                category=category,
                support="unsupported",
                forbidden=[forbidden],
                refused=True,
                evidence_min=0,
                source_text=source_text,
                source_check=source_check,
            )
        )

    return cases


def main() -> None:
    cases = build_cases()
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT.open("w", encoding="utf-8") as handle:
        for item in cases:
            handle.write(json.dumps(item, ensure_ascii=False, sort_keys=True) + "\n")


if __name__ == "__main__":
    main()

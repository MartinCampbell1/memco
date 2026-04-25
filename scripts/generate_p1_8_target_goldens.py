from __future__ import annotations

import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
GOLDENS = ROOT / "eval" / "personal_memory_goldens"
OUTPUT = GOLDENS / "p1_8_target_personal_memory_goldens.jsonl"
MANIFEST = GOLDENS / "locomo_like_suite_manifest.json"
CONVERSATIONS = GOLDENS / "locomo_like_conversations.json"
NOW = "2026-04-24T00:00:00Z"
CONVERSATION_IDS = [f"locomo_like_{index:03d}" for index in range(1, 11)]


def _conversation_id(index: int) -> str:
    return CONVERSATION_IDS[(index - 1) % len(CONVERSATION_IDS)]


def fact(
    *,
    slug: str,
    name: str,
    key: str,
    domain: str,
    category: str,
    payload: dict[str, Any],
    summary: str,
    status: str = "active",
    event_at: str = "",
) -> dict[str, Any]:
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
        "valid_from": "",
    }


def case(
    *,
    case_id: str,
    index: int,
    group: str,
    slug: str,
    name: str,
    query: str,
    domain: str,
    category: str,
    expected: list[str] | None = None,
    forbidden: list[str] | None = None,
    facts: list[dict[str, Any]] | None = None,
    refused: bool = False,
    support: str = "supported",
    temporal_mode: str = "auto",
    scenario: str = "p1_8_target",
) -> dict[str, Any]:
    return {
        "conversation_id": _conversation_id(index),
        "domain": domain,
        "domain_category": category,
        "expect_refused": refused,
        "expected_evidence_count_min": 0 if refused else 1,
        "expected_support_level": support,
        "expected_values": expected or [],
        "forbidden_values": forbidden or [],
        "group": group,
        "id": case_id,
        "limit": 3,
        "person_display_name": name,
        "person_slug": slug,
        "query": query,
        "scenario": scenario,
        "seed_facts": facts or [],
        "temporal_mode": temporal_mode,
    }


def build_cases() -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []
    serial = 1

    for index in range(1, 26):
        slug = f"p1-8-preference-{index:03d}"
        name = f"P18 Preference {index:03d}"
        value = f"current preference marker {index:03d}"
        old_value = f"old preference marker {index:03d}"
        cases.append(
            case(
                case_id=f"p1_8_preference_{index:03d}",
                index=serial,
                group="preference",
                slug=slug,
                name=name,
                query=f"What does {name} prefer now?",
                domain="preferences",
                category="preference",
                expected=[value],
                temporal_mode="current",
                facts=[
                    fact(
                        slug=slug,
                        name=name,
                        key="preference/old",
                        domain="preferences",
                        category="preference",
                        payload={"value": old_value, "is_current": False},
                        summary=f"{name} used to prefer {old_value}.",
                        status="deleted",
                    ),
                    fact(
                        slug=slug,
                        name=name,
                        key="preference/current",
                        domain="preferences",
                        category="preference",
                        payload={"value": value, "is_current": True},
                        summary=f"{name} prefers {value} now after previously preferring {old_value}.",
                    )
                ],
                scenario="p1_8_preference_current_state",
            )
        )
        serial += 1

    for index in range(1, 26):
        slug = f"p1-8-social-{index:03d}"
        name = f"P18 Social {index:03d}"
        relation = "friend" if index % 2 else "sister"
        target = f"P18 Contact {index:03d}"
        cases.append(
            case(
                case_id=f"p1_8_social_{index:03d}",
                index=serial,
                group="social_family",
                slug=slug,
                name=name,
                query=f"Who is {name}'s {relation}?",
                domain="social_circle",
                category=relation,
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
                scenario="p1_8_social_graph",
            )
        )
        serial += 1

    for index in range(1, 76):
        slug = f"p1-8-work-{index:03d}"
        name = f"P18 Work {index:03d}"
        category = "tool" if index % 2 else "project"
        value = f"P18Tool{index:03d}" if category == "tool" else f"P18Project{index:03d}"
        verb = "uses" if category == "tool" else "shipped"
        cases.append(
            case(
                case_id=f"p1_8_work_{index:03d}",
                index=serial,
                group="core_fact",
                slug=slug,
                name=name,
                query=f"What {category} is recorded for {name}?",
                domain="work",
                category=category,
                expected=[value],
                facts=[
                    fact(
                        slug=slug,
                        name=name,
                        key=f"work/{category}",
                        domain="work",
                        category=category,
                        payload={category: value},
                        summary=f"{name} {verb} {value}.",
                    )
                ],
                scenario="p1_8_work_project_tool",
            )
        )
        serial += 1

    for index in range(1, 6):
        slug = f"p1-8-temporal-{index:03d}"
        name = f"P18 Temporal {index:03d}"
        event = f"P18 Temporal Event {index:03d}"
        event_at = f"2024-0{index}-20"
        cases.append(
            case(
                case_id=f"p1_8_temporal_{index:03d}",
                index=serial,
                group="temporal",
                slug=slug,
                name=name,
                query=f"When did {name} attend {event}?",
                domain="experiences",
                category="event",
                expected=[event_at],
                temporal_mode="when",
                facts=[
                    fact(
                        slug=slug,
                        name=name,
                        key="experience/event",
                        domain="experiences",
                        category="event",
                        payload={"event": event, "event_at": event_at},
                        summary=f"{name} attended {event} on {event_at}.",
                        event_at=event_at,
                    )
                ],
                scenario="p1_8_experiences_temporal",
            )
        )
        serial += 1

    for index in range(1, 26):
        slug = f"p1-8-adversarial-{index:03d}"
        name = f"P18 Adversarial {index:03d}"
        true_city = f"TrueCity{index:03d}"
        false_city = f"FalseCity{index:03d}"
        cases.append(
            case(
                case_id=f"p1_8_adversarial_{index:03d}",
                index=serial,
                group="adversarial_false_premise",
                slug=slug,
                name=name,
                query=f"Does {name} live in {false_city}?",
                domain="biography",
                category="residence",
                forbidden=[false_city],
                refused=True,
                support="contradicted",
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
                scenario="p1_8_adversarial_false_premise",
            )
        )
        serial += 1

    for index in range(1, 6):
        slug = f"p1-8-update-{index:03d}"
        name = f"P18 Update {index:03d}"
        old_city = f"OldP18City{index:03d}"
        current_city = f"CurrentP18City{index:03d}"
        cases.append(
            case(
                case_id=f"p1_8_update_{index:03d}",
                index=serial,
                group="rollback_update",
                slug=slug,
                name=name,
                query=f"Where does {name} live now?",
                domain="biography",
                category="residence",
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
                scenario="p1_8_update_supersession",
            )
        )
        serial += 1

    return cases


def _load_all_cases() -> list[dict[str, Any]]:
    loaded: list[dict[str, Any]] = []
    for path in sorted(GOLDENS.glob("*.jsonl")):
        with path.open("r", encoding="utf-8") as handle:
            for raw in handle:
                if raw.strip():
                    loaded.append(json.loads(raw))
    return loaded


def _turn_text(case_item: dict[str, Any]) -> str:
    facts = case_item.get("seed_facts") or []
    if facts:
        return str(facts[0].get("quote_text") or facts[0].get("summary") or case_item["query"])
    return str(case_item["query"])


def refresh_locomo_like_metadata(cases: list[dict[str, Any]]) -> None:
    grouped: dict[str, list[dict[str, Any]]] = {conversation_id: [] for conversation_id in CONVERSATION_IDS}
    for item in cases:
        grouped.setdefault(str(item["conversation_id"]), []).append(item)

    manifest_conversations: list[dict[str, Any]] = []
    fixture_conversations: list[dict[str, Any]] = []
    for conversation_id in sorted(grouped):
        items = grouped[conversation_id]
        people = {
            str(fact.get("person_slug") or item["person_slug"]): str(
                fact.get("person_display_name") or item["person_display_name"]
            )
            for item in items
            for fact in (item.get("seed_facts") or [{"person_slug": item["person_slug"], "person_display_name": item["person_display_name"]}])
        }
        turns = []
        seen: set[str] = set()
        for item in items:
            slug = str(item["person_slug"])
            if slug in seen:
                continue
            seen.add(slug)
            turns.append(
                {
                    "speaker_display_name": str(item["person_display_name"]),
                    "speaker_slug": slug,
                    "text": _turn_text(item),
                    "turn_index": len(turns) + 1,
                }
            )
        for slug, display_name in sorted(people.items()):
            if slug in seen:
                continue
            seen.add(slug)
            turns.append(
                {
                    "speaker_display_name": display_name,
                    "speaker_slug": slug,
                    "text": f"{display_name} appears in linked personal-memory evidence for {conversation_id}.",
                    "turn_index": len(turns) + 1,
                }
            )
        speaker_cycle = list(turns) or [
            {
                "speaker_display_name": "Personal Alice",
                "speaker_slug": "personal-alice",
                "text": f"Personal Alice adds follow-up context for {conversation_id}.",
                "turn_index": 1,
            }
        ]
        while len(turns) < 50:
            speaker = speaker_cycle[len(turns) % len(speaker_cycle)]
            turns.append(
                {
                    "speaker_display_name": speaker["speaker_display_name"],
                    "speaker_slug": speaker["speaker_slug"],
                    "text": f"{speaker['speaker_display_name']} adds follow-up context for {conversation_id} turn {len(turns) + 1}.",
                    "turn_index": len(turns) + 1,
                }
            )
        person_slugs = sorted({str(turn["speaker_slug"]) for turn in turns})
        linked_case_ids = sorted(str(item["id"]) for item in items)
        coverage = sorted(
            {
                coverage
                for item in items
                for coverage in _coverage_for_case(item)
            }
        )
        manifest_conversations.append(
            {
                "conversation_id": conversation_id,
                "coverage": coverage,
                "linked_case_ids": linked_case_ids,
                "person_slugs": person_slugs,
                "turn_count": len(turns),
            }
        )
        fixture_conversations.append(
            {
                "conversation_id": conversation_id,
                "coverage": coverage,
                "linked_case_ids": linked_case_ids,
                "person_slugs": person_slugs,
                "turn_count": len(turns),
                "turns": turns,
            }
        )

    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    manifest["conversations"] = manifest_conversations
    MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    CONVERSATIONS.write_text(
        json.dumps({"conversations": fixture_conversations}, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _coverage_for_case(item: dict[str, Any]) -> set[str]:
    group = str(item.get("group") or "")
    domain = str(item.get("domain") or "")
    coverage: set[str] = set()
    if group in {"core_fact", "preference", "speakerless_note"}:
        coverage.add("single_hop")
    if group == "social_family":
        coverage.add("multi_hop")
    if group in {"temporal", "rollback_update"} or domain == "experiences":
        coverage.add("temporal")
    if group == "speakerless_note":
        coverage.add("open_inference")
    if group == "adversarial_false_premise":
        coverage.add("adversarial_false_premise")
    if group == "cross_person_contamination":
        coverage.add("cross_person")
    return coverage or {"single_hop"}


def main() -> None:
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    new_cases = build_cases()
    with OUTPUT.open("w", encoding="utf-8") as handle:
        for item in new_cases:
            handle.write(json.dumps(item, ensure_ascii=False, sort_keys=True) + "\n")
    refresh_locomo_like_metadata(_load_all_cases())
    print(f"wrote {len(new_cases)} cases to {OUTPUT}")


if __name__ == "__main__":
    main()

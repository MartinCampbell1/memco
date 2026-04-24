from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "eval" / "personal_memory_goldens" / "synthetic_personal_memory_goldens.jsonl"
ALICE = {"person_slug": "personal-alice", "person_display_name": "Personal Alice"}
BOB = {"person_slug": "personal-bob", "person_display_name": "Personal Bob"}


def fact(
    *,
    person: dict,
    domain: str,
    category: str,
    canonical_key: str,
    payload: dict,
    summary: str,
    quote_text: str | None = None,
    status: str = "active",
    observed_at: str = "2026-04-24T00:00:00Z",
    valid_from: str = "",
    event_at: str = "",
) -> dict:
    return {
        "person_slug": person["person_slug"],
        "person_display_name": person["person_display_name"],
        "domain": domain,
        "category": category,
        "canonical_key": canonical_key,
        "payload": payload,
        "summary": summary,
        "quote_text": quote_text or summary,
        "status": status,
        "observed_at": observed_at,
        "valid_from": valid_from,
        "event_at": event_at,
    }


def case(
    *,
    case_id: str,
    group: str,
    person: dict,
    query: str,
    domain: str,
    domain_category: str,
    expect_refused: bool,
    expected_values: list[str],
    seed_facts: list[dict],
    forbidden_values: list[str] | None = None,
    expected_support_level: str = "supported",
    temporal_mode: str = "auto",
) -> dict:
    return {
        "id": case_id,
        "group": group,
        "person_slug": person["person_slug"],
        "person_display_name": person["person_display_name"],
        "query": query,
        "domain": domain,
        "domain_category": domain_category,
        "temporal_mode": temporal_mode,
        "expect_refused": expect_refused,
        "expected_support_level": expected_support_level,
        "expected_values": expected_values,
        "forbidden_values": forbidden_values or [],
        "expected_evidence_count_min": 1 if not expect_refused else 0,
        "seed_facts": seed_facts,
    }


def build_cases() -> list[dict]:
    cases: list[dict] = []
    for index in range(1, 101):
        token = f"core-value-{index:03d}"
        summary = f"Personal Alice core fact {index:03d} is {token}."
        cases.append(
            case(
                case_id=f"core_fact_{index:03d}",
                group="core_fact",
                person=ALICE,
                query=f"What is Personal Alice core fact {index:03d}?",
                domain="biography",
                domain_category="other_stable_self_knowledge",
                expect_refused=False,
                expected_values=[token],
                seed_facts=[
                    fact(
                        person=ALICE,
                        domain="biography",
                        category="other_stable_self_knowledge",
                        canonical_key=f"personal-alice:core:{index:03d}",
                        payload={"fact": token},
                        summary=summary,
                    )
                ],
            )
        )
    for index in range(1, 51):
        true_city = f"LisbonAdv{index:03d}"
        false_city = f"BerlinAdv{index:03d}"
        cases.append(
            case(
                case_id=f"adversarial_false_premise_{index:03d}",
                group="adversarial_false_premise",
                person=ALICE,
                query=f"Does Personal Alice live in {false_city}?",
                domain="biography",
                domain_category="residence",
                expect_refused=True,
                expected_support_level="contradicted",
                expected_values=[],
                forbidden_values=[false_city],
                seed_facts=[
                    fact(
                        person=ALICE,
                        domain="biography",
                        category="residence",
                        canonical_key=f"personal-alice:adversarial-residence:{index:03d}",
                        payload={"city": true_city},
                        summary=f"Personal Alice lives in {true_city}.",
                    )
                ],
            )
        )
    for index in range(1, 51):
        relation = "sister" if index % 2 else "friend"
        target = f"SocialName{index:03d}"
        cases.append(
            case(
                case_id=f"social_family_{index:03d}",
                group="social_family",
                person=ALICE,
                query=f"Who is Personal Alice's {relation} {index:03d}?",
                domain="social_circle",
                domain_category=relation,
                expect_refused=False,
                expected_values=[target],
                seed_facts=[
                    fact(
                        person=ALICE,
                        domain="social_circle",
                        category=relation,
                        canonical_key=f"personal-alice:{relation}:{index:03d}",
                        payload={"relation": relation, "target_label": target},
                        summary=f"Personal Alice's {relation} {index:03d} is {target}.",
                    )
                ],
            )
        )
    for index in range(1, 51):
        event = f"TemporalEvent{index:03d}"
        event_at = f"2024-{((index - 1) % 12) + 1:02d}-01"
        cases.append(
            case(
                case_id=f"temporal_{index:03d}",
                group="temporal",
                person=ALICE,
                query=f"When did Personal Alice attend {event}?",
                domain="experiences",
                domain_category="event",
                temporal_mode="when",
                expect_refused=False,
                expected_values=[event_at],
                seed_facts=[
                    fact(
                        person=ALICE,
                        domain="experiences",
                        category="event",
                        canonical_key=f"personal-alice:event:{index:03d}",
                        payload={"event": event, "event_at": event_at},
                        summary=f"Personal Alice attended {event}.",
                        event_at=event_at,
                    )
                ],
            )
        )
    for index in range(1, 51):
        preference_person = {
            "person_slug": f"personal-preference-{index:03d}",
            "person_display_name": f"Personal Preference {index:03d}",
        }
        value = f"PreferenceValue{index:03d}"
        cases.append(
            case(
                case_id=f"preference_{index:03d}",
                group="preference",
                person=preference_person,
                query=f"What is Personal Preference {index:03d} preference?",
                domain="preferences",
                domain_category="preference",
                expect_refused=False,
                expected_values=[value],
                seed_facts=[
                    fact(
                        person=preference_person,
                        domain="preferences",
                        category="preference",
                        canonical_key=f"personal-preference-{index:03d}:preference",
                        payload={"value": value},
                        summary=f"Personal Preference {index:03d} preference is {value}.",
                    )
                ],
            )
        )
    for index in range(1, 31):
        cross_alice = {
            "person_slug": f"personal-cross-alice-{index:03d}",
            "person_display_name": f"Personal Cross Alice {index:03d}",
        }
        cross_bob = {
            "person_slug": f"personal-cross-bob-{index:03d}",
            "person_display_name": f"Personal Cross Bob {index:03d}",
        }
        alice_value = f"AliceIso{index:03d}"
        bob_value = f"BobIso{index:03d}"
        cases.append(
            case(
                case_id=f"cross_person_contamination_{index:03d}",
                group="cross_person_contamination",
                person=cross_alice,
                query=f"What is Personal Cross Alice {index:03d} isolation preference?",
                domain="preferences",
                domain_category="preference",
                expect_refused=False,
                expected_values=[alice_value],
                forbidden_values=[bob_value],
                seed_facts=[
                    fact(
                        person=cross_alice,
                        domain="preferences",
                        category="preference",
                        canonical_key=f"personal-cross-alice-{index:03d}:isolation",
                        payload={"value": alice_value},
                        summary=f"Personal Cross Alice {index:03d} isolation preference is {alice_value}.",
                    ),
                    fact(
                        person=cross_bob,
                        domain="preferences",
                        category="preference",
                        canonical_key=f"personal-cross-bob-{index:03d}:isolation",
                        payload={"value": bob_value},
                        summary=f"Personal Cross Bob {index:03d} isolation preference is {bob_value}.",
                    ),
                ],
            )
        )
    for index in range(1, 31):
        value = f"speakerless-owner-value-{index:03d}"
        cases.append(
            case(
                case_id=f"speakerless_note_{index:03d}",
                group="speakerless_note",
                person=ALICE,
                query=f"What did speakerless note {index:03d} say about Personal Alice?",
                domain="biography",
                domain_category="other_stable_self_knowledge",
                expect_refused=False,
                expected_values=[value],
                seed_facts=[
                    fact(
                        person=ALICE,
                        domain="biography",
                        category="other_stable_self_knowledge",
                        canonical_key=f"personal-alice:speakerless-note:{index:03d}",
                        payload={"fact": value, "attribution_method": "owner_first_person_fallback"},
                        summary=f"Personal Alice speakerless note {index:03d} says {value}.",
                    )
                ],
            )
        )
    for index in range(1, 21):
        rollback_person = {
            "person_slug": f"personal-rollback-{index:03d}",
            "person_display_name": f"Personal Rollback {index:03d}",
        }
        old_city = f"OldCity{index:03d}"
        current_city = f"CurrentCity{index:03d}"
        cases.append(
            case(
                case_id=f"rollback_update_{index:03d}",
                group="rollback_update",
                person=rollback_person,
                query=f"Where does Personal Rollback {index:03d} live now?",
                domain="biography",
                domain_category="residence",
                temporal_mode="current",
                expect_refused=False,
                expected_values=[current_city],
                forbidden_values=[old_city],
                seed_facts=[
                    fact(
                        person=rollback_person,
                        domain="biography",
                        category="residence",
                        canonical_key=f"personal-rollback-{index:03d}:old",
                        payload={"city": old_city},
                        summary=f"Personal Rollback {index:03d} lives in {old_city}.",
                        status="deleted",
                    ),
                    fact(
                        person=rollback_person,
                        domain="biography",
                        category="residence",
                        canonical_key=f"personal-rollback-{index:03d}:current",
                        payload={"city": current_city},
                        summary=f"Personal Rollback {index:03d} lives in {current_city}.",
                    ),
                ],
            )
        )
    return cases


def main() -> None:
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    cases = build_cases()
    with OUTPUT.open("w", encoding="utf-8") as handle:
        for item in cases:
            handle.write(json.dumps(item, ensure_ascii=False, sort_keys=True) + "\n")
    print(f"wrote {len(cases)} cases to {OUTPUT}")


if __name__ == "__main__":
    main()

from __future__ import annotations

import json
import re

from memco.config import Settings
from memco.llm import LLMProvider, MockLLMProvider, build_llm_provider
from memco.llm_usage import LLMUsageEvent, LLMUsageFileLogger, LLMUsageTracker
from memco.utils import slugify


RESIDENCE_PATTERNS = (
    re.compile(r"\bi\s+(?:currently\s+)?live\s+in\s+(?P<value>[^.!?\n]+)", re.IGNORECASE),
    re.compile(r"\bi\s+moved\s+to\s+(?P<value>[^.!?\n]+)", re.IGNORECASE),
    re.compile(r"\bi(?:'m| am)\s+from\s+(?P<value>[^.!?\n]+)", re.IGNORECASE),
)

PREFERENCE_PATTERNS = (
    ("prefer", re.compile(r"\bi\s+prefer\s+(?P<value>[^.!?\n]+)", re.IGNORECASE)),
    ("like", re.compile(r"\bi\s+like\s+(?P<value>[^.!?\n]+)", re.IGNORECASE)),
)

SOCIAL_PATTERN = re.compile(
    r"\b(?P<target>[a-zA-Z][a-zA-Z0-9'\- ]{0,80})\s+is\s+my\s+"
    r"(?P<relation>friend|brother|sister|wife|husband|partner|mother|father|mom|dad|son|daughter|colleague|boss|roommate|neighbor)\b",
    re.IGNORECASE,
)

WORK_ROLE_PATTERNS = (
    re.compile(r"\bi\s+work\s+as\s+(?:an?\s+)?(?P<value>[^.!?\n]+)", re.IGNORECASE),
    re.compile(r"\bi(?:'m| am)\s+(?:an?\s+)?(?P<value>(?:engineer|designer|manager|developer|teacher|writer|analyst|researcher)[^.!?\n]*)", re.IGNORECASE),
)

WORK_SKILL_PATTERNS = (
    re.compile(r"\bi\s+(?:use|work with)\s+(?P<value>[^.!?\n]+)", re.IGNORECASE),
    re.compile(r"\bi\s+know\s+(?P<value>[^.!?\n]+)", re.IGNORECASE),
)

EXPERIENCE_PATTERNS = (
    re.compile(r"\bi\s+went\s+to\s+(?P<value>[^.!?\n]+)", re.IGNORECASE),
    re.compile(r"\bi\s+visited\s+(?P<value>[^.!?\n]+)", re.IGNORECASE),
    re.compile(r"\bi\s+attended\s+(?P<value>[^.!?\n]+)", re.IGNORECASE),
)

STYLE_MARKERS = {
    "humorous": ("haha", "lol", "joke", "funny"),
    "warm": ("thanks", "thank you", "glad", "appreciate"),
    "direct": ("please do", "just", "need", "must"),
}

PSYCHOMETRIC_PATTERNS = (
    ("big_five", "openness", re.compile(r"\bi(?:'m| am)\s+(?:very\s+)?curious\b", re.IGNORECASE), "high"),
    ("schwartz_values", "self_direction", re.compile(r"\bi\s+value\s+independence\b", re.IGNORECASE), "high"),
)


def _clean_value(value: str) -> str:
    cleaned = value.strip().strip(".,!?;:").strip()
    return re.sub(r"\s+", " ", cleaned)


def _subject_key(person_id: int | None, speaker_label: str, person_hint: str | None = None) -> str:
    if person_id is not None:
        return f"p{person_id}"
    fallback = speaker_label or person_hint or "unknown"
    return slugify(fallback)


def _display_subject(speaker_label: str, person_id: int | None) -> str:
    if speaker_label:
        return speaker_label
    if person_id is not None:
        return f"Person {person_id}"
    return "Unknown speaker"


class ExtractionService:
    def __init__(
        self,
        *,
        settings: Settings | None = None,
        llm_provider: LLMProvider | None = None,
        usage_tracker: LLMUsageTracker | None = None,
    ) -> None:
        self._settings = settings
        self.usage_tracker = usage_tracker or LLMUsageTracker()
        self.usage_file_logger = (
            LLMUsageFileLogger(settings.root / "var" / "log" / "llm_usage.jsonl")
            if settings is not None
            else None
        )
        self.llm_provider = llm_provider or self._build_provider()

    @classmethod
    def from_settings(cls, settings: Settings, *, usage_tracker: LLMUsageTracker | None = None) -> "ExtractionService":
        return cls(settings=settings, usage_tracker=usage_tracker)

    def _build_provider(self) -> LLMProvider:
        if self._settings is None:
            return MockLLMProvider(
                json_handler=self._mock_complete_json,
                text_handler=self._mock_complete_text,
            )
        settings = self._settings
        return build_llm_provider(
            settings,
            json_handler=self._mock_complete_json,
            text_handler=self._mock_complete_text,
        )

    def _extraction_system_prompt(self, *, include_style: bool, include_psychometrics: bool) -> str:
        return (
            "Extract persona-memory candidates as strict JSON. "
            "Return a JSON array. "
            f"include_style={str(include_style).lower()} "
            f"include_psychometrics={str(include_psychometrics).lower()}."
        )

    def _extraction_prompt(
        self,
        *,
        text: str,
        subject_key: str,
        subject_display: str,
        speaker_label: str,
        person_id: int | None,
        message_id: int | None,
        source_segment_id: int | None,
        occurred_at: str,
        include_style: bool,
        include_psychometrics: bool,
    ) -> str:
        return json.dumps(
            {
                "text": text,
                "subject_key": subject_key,
                "subject_display": subject_display,
                "speaker_label": speaker_label,
                "person_id": person_id,
                "message_id": message_id,
                "source_segment_id": source_segment_id,
                "occurred_at": occurred_at,
                "include_style": include_style,
                "include_psychometrics": include_psychometrics,
            },
            ensure_ascii=False,
        )

    def _mock_complete_json(
        self,
        *,
        system_prompt: str,
        prompt: str,
        schema_name: str,
        metadata: dict,
    ) -> list[dict]:
        if schema_name != "memory_fact_candidates":
            raise ValueError(f"Unsupported mock JSON schema: {schema_name}")
        return self._extract_from_text(
            text=metadata["text"],
            subject_key=metadata["subject_key"],
            subject_display=metadata["subject_display"],
            speaker_label=metadata["speaker_label"],
            person_id=metadata["person_id"],
            conn=metadata["conn"],
            workspace_id=metadata["workspace_id"],
            message_id=metadata["message_id"],
            source_segment_id=metadata["source_segment_id"],
            occurred_at=metadata["occurred_at"],
            include_style=metadata["include_style"],
            include_psychometrics=metadata["include_psychometrics"],
        )

    def _mock_complete_text(self, *, system_prompt: str, prompt: str, metadata: dict) -> str:
        return prompt

    def _record_usage(self, *, operation: str, metadata: dict, usage) -> None:
        event = LLMUsageEvent(
            provider=self.llm_provider.name,
            model=self.llm_provider.model,
            operation=operation,
            input_tokens=int(usage.input_tokens),
            output_tokens=int(usage.output_tokens),
            estimated_cost_usd=usage.estimated_cost_usd,
            deterministic=self.llm_provider.name == "mock",
            metadata={
                "schema_name": metadata.get("schema_name"),
                "message_id": metadata.get("message_id"),
                "workspace_id": metadata.get("workspace_id"),
                "has_person_id": metadata.get("person_id") is not None,
                "include_style": bool(metadata.get("include_style")),
                "include_psychometrics": bool(metadata.get("include_psychometrics")),
            },
        )
        self.usage_tracker.record(event)
        if self.usage_file_logger is not None:
            self.usage_file_logger.record(event)

    def _extract_candidates_via_provider(
        self,
        *,
        text: str,
        subject_key: str,
        subject_display: str,
        speaker_label: str,
        person_id: int | None,
        conn,
        workspace_id: int | None,
        message_id: int | None = None,
        source_segment_id: int | None = None,
        occurred_at: str = "",
        include_style: bool = False,
        include_psychometrics: bool = False,
    ) -> list[dict]:
        metadata = {
            "text": text,
            "subject_key": subject_key,
            "subject_display": subject_display,
            "speaker_label": speaker_label,
            "person_id": person_id,
            "conn": conn,
            "workspace_id": workspace_id,
            "message_id": message_id,
            "source_segment_id": source_segment_id,
            "occurred_at": occurred_at,
            "include_style": include_style,
            "include_psychometrics": include_psychometrics,
        }
        response = self.llm_provider.complete_json(
            system_prompt=self._extraction_system_prompt(
                include_style=include_style,
                include_psychometrics=include_psychometrics,
            ),
            prompt=self._extraction_prompt(
                text=text,
                subject_key=subject_key,
                subject_display=subject_display,
                speaker_label=speaker_label,
                person_id=person_id,
                message_id=message_id,
                source_segment_id=source_segment_id,
                occurred_at=occurred_at,
                include_style=include_style,
                include_psychometrics=include_psychometrics,
            ),
            schema_name="memory_fact_candidates",
            metadata=metadata,
        )
        self._record_usage(
            operation="complete_json",
            metadata={**metadata, "schema_name": "memory_fact_candidates"},
            usage=response.usage,
        )
        content = response.content
        if isinstance(content, dict) and isinstance(content.get("items"), list):
            content = content["items"]
        if not isinstance(content, list):
            raise ValueError("LLM provider returned non-list candidate payload")
        return content

    def extract_candidates(self, *, source_text: str, person_hint: str | None = None) -> list[dict]:
        text = source_text.strip()
        if not text:
            return []
        subject_key = _subject_key(None, person_hint or "", person_hint)
        subject_display = _display_subject(person_hint or "", None)
        return self._extract_candidates_via_provider(
            text=text,
            subject_key=subject_key,
            subject_display=subject_display,
            speaker_label=person_hint or "",
            person_id=None,
            workspace_id=None,
            conn=None,
        )

    def _resolve_person_id(self, conn, *, workspace_id: int, label: str) -> int | None:
        normalized = " ".join(label.strip().lower().split())
        if not normalized:
            return None
        row = conn.execute(
            """
            SELECT person_id
            FROM person_aliases
            WHERE workspace_id = ? AND normalized_alias = ? AND alias_type = 'name'
            """,
            (workspace_id, normalized),
        ).fetchone()
        if row is None:
            return None
        return int(row["person_id"])

    def _extract_from_text(
        self,
        *,
        text: str,
        subject_key: str,
        subject_display: str,
        speaker_label: str,
        person_id: int | None,
        conn,
        workspace_id: int | None,
        message_id: int | None = None,
        source_segment_id: int | None = None,
        occurred_at: str = "",
        include_style: bool = False,
        include_psychometrics: bool = False,
    ) -> list[dict]:
        candidates: list[dict] = []
        evidence = [
            {
                "quote": text.strip(),
                "message_ids": [str(message_id)] if message_id is not None else [],
                "source_segment_ids": [int(source_segment_id)] if source_segment_id is not None else [],
                "chunk_kind": "conversation",
            }
        ]

        for pattern in RESIDENCE_PATTERNS:
            match = pattern.search(text)
            if not match:
                continue
            city = _clean_value(match.group("value"))
            if not city:
                continue
            review_reasons: list[str] = []
            if person_id is None:
                review_reasons.append("speaker_unresolved")
            candidates.append(
                {
                    "domain": "biography",
                    "category": "residence",
                    "subcategory": "",
                    "canonical_key": f"{subject_key}:biography:residence:{slugify(city)}",
                    "payload": {"city": city},
                    "summary": f"{subject_display} lives in {city}.",
                    "confidence": 0.9 if person_id is not None else 0.65,
                    "reason": ",".join(review_reasons),
                    "needs_review": bool(review_reasons),
                    "evidence": evidence,
                }
            )
            break

        for verb, pattern in PREFERENCE_PATTERNS:
            match = pattern.search(text)
            if not match:
                continue
            value = _clean_value(match.group("value"))
            if not value:
                continue
            review_reasons: list[str] = []
            if person_id is None:
                review_reasons.append("speaker_unresolved")
            action = "prefers" if verb == "prefer" else "likes"
            candidates.append(
                {
                    "domain": "preferences",
                    "category": "preference",
                    "subcategory": "",
                    "canonical_key": f"{subject_key}:preferences:preference:{slugify(value)}",
                    "payload": {"value": value},
                    "summary": f"{subject_display} {action} {value}.",
                    "confidence": 0.85 if person_id is not None else 0.6,
                    "reason": ",".join(review_reasons),
                    "needs_review": bool(review_reasons),
                    "evidence": evidence,
                }
            )
            break

        social_match = SOCIAL_PATTERN.search(text)
        if social_match:
            target_label = _clean_value(social_match.group("target"))
            relation = _clean_value(social_match.group("relation")).lower()
            review_reasons: list[str] = []
            target_person_id = None
            if person_id is None:
                review_reasons.append("speaker_unresolved")
            if conn is not None and workspace_id is not None:
                target_person_id = self._resolve_person_id(
                    conn,
                    workspace_id=workspace_id,
                    label=target_label,
                )
            if target_person_id is None:
                review_reasons.append("relation_target_unresolved")
            candidates.append(
                {
                    "domain": "social_circle",
                    "category": relation,
                    "subcategory": "",
                    "canonical_key": f"{subject_key}:social_circle:{relation}:{slugify(target_label)}",
                    "payload": {
                        "relation": relation,
                        "target_label": target_label,
                        "target_person_id": target_person_id,
                    },
                    "summary": f"{subject_display} says {target_label} is their {relation}.",
                    "confidence": 0.8 if not review_reasons else 0.55,
                    "reason": ",".join(review_reasons),
                    "needs_review": bool(review_reasons),
                    "evidence": evidence,
                }
            )

        for pattern in WORK_ROLE_PATTERNS:
            match = pattern.search(text)
            if not match:
                continue
            title = _clean_value(match.group("value"))
            if not title:
                continue
            review_reasons: list[str] = []
            if person_id is None:
                review_reasons.append("speaker_unresolved")
            candidates.append(
                {
                    "domain": "work",
                    "category": "employment",
                    "subcategory": "",
                    "canonical_key": f"{subject_key}:work:employment:{slugify(title)}",
                    "payload": {"title": title},
                    "summary": f"{subject_display} works as {title}.",
                    "confidence": 0.82 if person_id is not None else 0.58,
                    "reason": ",".join(review_reasons),
                    "needs_review": bool(review_reasons),
                    "evidence": evidence,
                }
            )
            break

        for pattern in WORK_SKILL_PATTERNS:
            match = pattern.search(text)
            if not match:
                continue
            skill = _clean_value(match.group("value"))
            if not skill:
                continue
            review_reasons: list[str] = []
            if person_id is None:
                review_reasons.append("speaker_unresolved")
            candidates.append(
                {
                    "domain": "work",
                    "category": "skill",
                    "subcategory": "",
                    "canonical_key": f"{subject_key}:work:skill:{slugify(skill)}",
                    "payload": {"skill": skill},
                    "summary": f"{subject_display} uses {skill}.",
                    "confidence": 0.72 if person_id is not None else 0.5,
                    "reason": ",".join(review_reasons),
                    "needs_review": bool(review_reasons),
                    "evidence": evidence,
                }
            )
            break

        for pattern in EXPERIENCE_PATTERNS:
            match = pattern.search(text)
            if not match:
                continue
            event = _clean_value(match.group("value"))
            if not event:
                continue
            review_reasons: list[str] = []
            if person_id is None:
                review_reasons.append("speaker_unresolved")
            candidates.append(
                {
                    "domain": "experiences",
                    "category": "event",
                    "subcategory": "",
                    "canonical_key": f"{subject_key}:experiences:event:{slugify(event)}",
                    "payload": {"event": event},
                    "summary": f"{subject_display} experienced {event}.",
                    "confidence": 0.78 if person_id is not None else 0.55,
                    "reason": ",".join(review_reasons),
                    "needs_review": bool(review_reasons),
                    "evidence": evidence,
                }
            )
            break

        if include_psychometrics:
            for framework, trait, pattern, direction in PSYCHOMETRIC_PATTERNS:
                if not pattern.search(text):
                    continue
                review_reasons: list[str] = []
                if person_id is None:
                    review_reasons.append("speaker_unresolved")
                candidates.append(
                    {
                        "domain": "psychometrics",
                        "category": "trait",
                        "subcategory": framework,
                        "canonical_key": f"{subject_key}:psychometrics:{framework}:{trait}",
                        "payload": {
                            "framework": framework,
                            "trait": trait,
                            "score": 0.7,
                            "score_scale": "0_1",
                            "direction": direction,
                            "confidence": 0.55 if person_id is not None else 0.4,
                            "evidence_quotes": [
                                {
                                    "quote": text.strip(),
                                    "message_ids": [str(message_id)] if message_id is not None else [],
                                    "interpretation": f"Possible signal for {trait}.",
                                }
                            ],
                            "counterevidence_quotes": [],
                            "last_updated": occurred_at or "",
                            "use_in_generation": True,
                            "safety_notes": "Non-diagnostic inferred psychometric stub.",
                        },
                        "summary": f"{subject_display} may show {trait} ({framework}).",
                        "confidence": 0.55 if person_id is not None else 0.4,
                        "reason": ",".join(review_reasons),
                        "needs_review": bool(review_reasons),
                        "evidence": evidence,
                    }
                )
                break

        if include_style:
            lowered = text.lower()
            tone = "unknown"
            for candidate_tone, markers in STYLE_MARKERS.items():
                if any(marker in lowered for marker in markers):
                    tone = candidate_tone
                    break
            if tone != "unknown":
                review_reasons: list[str] = []
                if person_id is None:
                    review_reasons.append("speaker_unresolved")
                candidates.append(
                    {
                        "domain": "style",
                        "category": "communication_style",
                        "subcategory": "",
                        "canonical_key": f"{subject_key}:style:communication_style:{tone}",
                        "payload": {
                            "tone": tone,
                            "verbosity": "medium",
                            "emoji_usage": "none",
                            "language_mix": [],
                            "signature_phrases": [],
                            "punctuation_style": None,
                            "generation_guidance": f"Lean {tone} but do not use this as factual evidence.",
                            "confidence": 0.6,
                        },
                        "summary": f"{subject_display} often communicates in a {tone} tone.",
                        "confidence": 0.6,
                        "reason": ",".join(review_reasons),
                        "needs_review": bool(review_reasons),
                        "evidence": evidence,
                    }
                )

        return candidates

    def extract_candidates_from_conversation(self, conn, *, conversation_id: int, include_style: bool = False, include_psychometrics: bool = False) -> list[dict]:
        rows = conn.execute(
            """
            SELECT
              c.id AS conversation_id,
              c.workspace_id,
              c.source_id,
              cm.id AS message_id,
              cm.message_index,
              cm.occurred_at,
              cm.text,
              cm.speaker_label,
              cm.speaker_person_id AS person_id,
              cc.id AS chunk_id,
              ss.id AS source_segment_id
            FROM conversations c
            JOIN conversation_messages cm
              ON cm.conversation_id = c.id
            LEFT JOIN conversation_chunks cc
              ON cc.conversation_id = c.id
             AND cm.message_index BETWEEN cc.start_message_index AND cc.end_message_index
            LEFT JOIN source_segments ss
              ON ss.message_id = cm.id
             AND ss.segment_type = 'message'
            WHERE c.id = ?
            ORDER BY cm.message_index ASC
            """,
            (conversation_id,),
        ).fetchall()
        candidates: list[dict] = []
        for row in rows:
            item = dict(row)
            speaker_label = item.get("speaker_label") or ""
            person_id = item.get("person_id")
            extracted = self._extract_candidates_via_provider(
                text=item.get("text") or "",
                subject_key=_subject_key(person_id, speaker_label),
                subject_display=_display_subject(speaker_label, person_id),
                speaker_label=speaker_label,
                person_id=person_id,
                conn=conn,
                workspace_id=int(item["workspace_id"]),
                message_id=int(item["message_id"]),
                source_segment_id=int(item["source_segment_id"]) if item.get("source_segment_id") is not None else None,
                occurred_at=item.get("occurred_at") or "",
                include_style=include_style,
                include_psychometrics=include_psychometrics,
            )
            for candidate in extracted:
                candidates.append(
                    {
                        "conversation_id": int(item["conversation_id"]),
                        "source_id": int(item["source_id"]),
                        "chunk_kind": "conversation",
                        "chunk_id": int(item["chunk_id"]) if item.get("chunk_id") is not None else None,
                        "person_id": person_id,
                        "speaker_label": speaker_label,
                        "text": item.get("text") or "",
                        "occurred_at": item.get("occurred_at") or "",
                        "message_id": int(item["message_id"]),
                        **candidate,
                    }
                )
        return candidates

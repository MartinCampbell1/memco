from __future__ import annotations

import json
import re
from typing import Any

from memco.config import Settings
from memco.extractors import ExtractionOrchestrator
from memco.extractors.base import (
    EXTRACTION_SCHEMA_NAME,
    ExtractionContext,
    build_extraction_system_prompt,
    build_prompt_payload,
    display_subject,
    subject_key,
    validate_candidate,
)
from memco.llm import LLMProvider, build_llm_provider
from memco.llm_usage import LLMUsageEvent, LLMUsageFileLogger, LLMUsageTracker
from memco.models.conversation import ExtractionChunk, MessageView
from memco.utils import slugify


FIRST_PERSON_RE = re.compile(
    r"\b(?:i|i'm|i’m|i've|i’ve|i'd|i’d|i'll|i’ll|me|my|mine)\b",
    re.IGNORECASE,
)
THIRD_PERSON_AMBIGUITY_RE = re.compile(
    r"(?i:\b(?:he|she|they|his|her|their)\b)|"
    r"\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+)?\s+"
    r"(?:lives|works|prefers|likes|loves|moved|has)\b"
)


class ExtractionService:
    def __init__(
        self,
        *,
        settings: Settings | None = None,
        llm_provider: LLMProvider | None = None,
        usage_tracker: LLMUsageTracker | None = None,
    ) -> None:
        if settings is None and llm_provider is None:
            raise ValueError("ExtractionService requires explicit settings or llm_provider; implicit mock fallback is fixture-only.")
        self._settings = settings
        self.orchestrator = ExtractionOrchestrator()
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
            raise ValueError("ExtractionService requires settings to build a runtime provider.")
        settings = self._settings
        return build_llm_provider(
            settings,
            json_handler=self._mock_complete_json,
            text_handler=self._mock_complete_text,
        )

    def _extraction_system_prompt(self, *, include_style: bool, include_psychometrics: bool) -> str:
        return build_extraction_system_prompt(
            include_style=include_style,
            include_psychometrics=include_psychometrics,
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
        session_id: int | None,
        occurred_at: str,
        include_style: bool,
        include_psychometrics: bool,
        chunk: ExtractionChunk | None = None,
        target_message_ids: list[int] | None = None,
    ) -> str:
        payload = build_prompt_payload(
            ExtractionContext(
                text=text,
                subject_key=subject_key,
                subject_display=subject_display,
                speaker_label=speaker_label,
                person_id=person_id,
                message_id=message_id,
                source_segment_id=source_segment_id,
                session_id=session_id,
                occurred_at=occurred_at,
            ),
            include_style=include_style,
            include_psychometrics=include_psychometrics,
        )
        if chunk is not None:
            payload["chunk"] = {
                "chunk_id": chunk.chunk_id,
                "chunk_kind": chunk.chunk_kind,
                "text": chunk.text,
                "source_segment_ids": chunk.source_segment_ids,
                "overlap_prev": chunk.overlap_prev,
                "overlap_next": chunk.overlap_next,
                "target_message_ids": target_message_ids or [],
                "messages": [message.model_dump(mode="json") for message in chunk.messages],
            }
        return json.dumps(payload, ensure_ascii=False)

    def _mock_complete_json(
        self,
        *,
        system_prompt: str,
        prompt: str,
        schema_name: str,
        metadata: dict,
    ) -> list[dict]:
        if schema_name != EXTRACTION_SCHEMA_NAME:
            raise ValueError(f"Unsupported mock JSON schema: {schema_name}")
        if metadata.get("chunk_kind") == "conversation" and metadata.get("chunk_id") is not None:
            return self._mock_extract_from_chunk(metadata)
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
            session_id=metadata["session_id"],
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
                "stage": "extraction",
                "schema_name": metadata.get("schema_name"),
                "message_id": metadata.get("message_id"),
                "source_id": metadata.get("source_id"),
                "chunk_id": metadata.get("chunk_id"),
                "workspace_id": metadata.get("workspace_id"),
                "person_id": metadata.get("person_id"),
                "has_person_id": metadata.get("person_id") is not None,
                "source_type": metadata.get("source_type"),
                "domains": metadata.get("candidate_domains", []),
                "candidate_count": int(metadata.get("candidate_count") or 0),
                "include_style": bool(metadata.get("include_style")),
                "include_psychometrics": bool(metadata.get("include_psychometrics")),
            },
        )
        self.usage_tracker.record(event)
        if self.usage_file_logger is not None:
            self.usage_file_logger.record(event)

    def _default_evidence_item(
        self,
        *,
        quote: str,
        message_id: int | None,
        source_segment_id: int | None,
        session_id: int | None,
        message_ids: list[int] | None = None,
        source_segment_ids: list[int] | None = None,
        session_ids: list[int] | None = None,
        chunk_kind: str = "conversation",
        attribution_method: str = "",
        attribution_confidence: float | None = None,
        source_type: str = "",
    ) -> dict[str, Any]:
        item = {
            "quote": quote.strip(),
            "message_ids": [str(message_id)] if message_id is not None else [str(item) for item in (message_ids or [])],
            "source_segment_ids": [int(source_segment_id)]
            if source_segment_id is not None
            else [int(item) for item in (source_segment_ids or [])],
            "session_ids": [int(session_id)] if session_id is not None else [int(item) for item in (session_ids or [])],
            "chunk_kind": chunk_kind,
        }
        if attribution_method:
            item["attribution_method"] = attribution_method
            item["attribution_confidence"] = attribution_confidence
            item["source_type"] = source_type
        return item

    def _normalize_provider_evidence(
        self,
        *,
        evidence: Any,
        fallback_quote: str,
        message_id: int | None,
        source_segment_id: int | None,
        session_id: int | None,
        fallback_message_ids: list[int] | None = None,
        fallback_source_segment_ids: list[int] | None = None,
        fallback_session_ids: list[int] | None = None,
        chunk_kind: str = "conversation",
        attribution_method: str = "",
        attribution_confidence: float | None = None,
        source_type: str = "",
    ) -> list[dict[str, Any]]:
        default_item = self._default_evidence_item(
            quote=fallback_quote,
            message_id=message_id,
            source_segment_id=source_segment_id,
            session_id=session_id,
            message_ids=fallback_message_ids,
            source_segment_ids=fallback_source_segment_ids,
            session_ids=fallback_session_ids,
            chunk_kind=chunk_kind,
            attribution_method=attribution_method,
            attribution_confidence=attribution_confidence,
            source_type=source_type,
        )
        if evidence is None:
            return []
        if isinstance(evidence, str) and evidence.strip():
            return [
                self._default_evidence_item(
                    quote=evidence,
                    message_id=message_id,
                    source_segment_id=source_segment_id,
                    session_id=session_id,
                    message_ids=fallback_message_ids,
                    source_segment_ids=fallback_source_segment_ids,
                    session_ids=fallback_session_ids,
                    chunk_kind=chunk_kind,
                    attribution_method=attribution_method,
                    attribution_confidence=attribution_confidence,
                    source_type=source_type,
                )
            ]
        if isinstance(evidence, list):
            if not evidence:
                return []
            normalized: list[dict[str, Any]] = []
            for item in evidence:
                if isinstance(item, str) and item.strip():
                    normalized.append(
                        self._default_evidence_item(
                            quote=item,
                            message_id=message_id,
                            source_segment_id=source_segment_id,
                            session_id=session_id,
                            message_ids=fallback_message_ids,
                            source_segment_ids=fallback_source_segment_ids,
                            session_ids=fallback_session_ids,
                            chunk_kind=chunk_kind,
                            attribution_method=attribution_method,
                            attribution_confidence=attribution_confidence,
                            source_type=source_type,
                        )
                    )
                    continue
                if not isinstance(item, dict):
                    continue
                quote = item.get("quote")
                if not isinstance(quote, str) or not quote.strip():
                    quote = fallback_quote
                evidence_item = {
                    "quote": quote.strip(),
                    "message_ids": item.get("message_ids")
                    if isinstance(item.get("message_ids"), list) and item.get("message_ids")
                    else list(default_item["message_ids"]),
                    "source_segment_ids": item.get("source_segment_ids")
                    if isinstance(item.get("source_segment_ids"), list) and item.get("source_segment_ids")
                    else list(default_item["source_segment_ids"]),
                    "session_ids": item.get("session_ids")
                    if isinstance(item.get("session_ids"), list) and item.get("session_ids")
                    else list(default_item["session_ids"]),
                    "chunk_kind": item.get("chunk_kind")
                    if isinstance(item.get("chunk_kind"), str) and item.get("chunk_kind", "").strip()
                    else default_item["chunk_kind"],
                }
                if attribution_method:
                    evidence_item["attribution_method"] = attribution_method
                    evidence_item["attribution_confidence"] = attribution_confidence
                    evidence_item["source_type"] = source_type
                normalized.append(evidence_item)
            if normalized:
                return normalized
        return []

    def _normalize_provider_candidate(
        self,
        *,
        candidate: dict[str, Any],
        text: str,
        subject_display: str,
        person_id: int | None,
        message_id: int | None,
        source_segment_id: int | None,
        session_id: int | None,
        fallback_message_ids: list[int] | None = None,
        fallback_source_segment_ids: list[int] | None = None,
        fallback_session_ids: list[int] | None = None,
        chunk_kind: str = "conversation",
        attribution_method: str = "",
        attribution_confidence: float | None = None,
        source_type: str = "",
    ) -> dict[str, Any]:
        normalized = dict(candidate)
        domain = str(normalized.get("domain") or "")
        payload = normalized.get("payload")
        if not isinstance(payload, dict):
            payload = {}
            normalized["payload"] = payload
        category = str(normalized.get("category") or "")
        optional_blank_string_fields = {
            ("preferences", "preference"): {
                "context",
                "original_phrasing",
                "preference_category",
                "preference_domain",
                "reason",
                "strength",
                "valid_from",
                "valid_to",
            },
            ("social_circle", "relationship_event"): {
                "context",
                "related_person_name",
                "relation_type",
                "sensitivity",
                "valence",
            },
            ("social_circle", "relationship"): {
                "related_person_name",
                "relation_type",
                "sensitivity",
                "valence",
            },
            ("work", "employment"): {
                "client",
                "constraints",
                "end_date",
                "org",
                "preferences",
                "role",
                "start_date",
                "status",
                "team",
            },
            ("work", "engagement"): {"client", "end_date", "org", "role", "start_date", "status", "team"},
            ("work", "role"): {"end_date", "start_date", "status"},
            ("work", "org"): {"client", "status"},
            ("work", "project"): {"end_date", "org", "role", "start_date", "status", "team"},
            ("work", "skill"): set(),
            ("work", "tool"): set(),
            ("experiences", "event"): {
                "date_range",
                "lesson",
                "location",
                "outcome",
                "recurrence",
                "summary",
                "temporal_anchor",
                "valence",
            },
        }
        removable_fields = optional_blank_string_fields.get((domain, category), set())
        for key in list(payload.keys()):
            value = payload.get(key)
            if key in removable_fields and (not isinstance(value, str) or not value.strip()):
                payload.pop(key, None)
        optional_list_fields = {
            ("experiences", "event"): {"linked_persons", "linked_projects", "participants"},
            ("social_circle", "relationship"): {"aliases"},
            ("social_circle", "relationship_event"): {"aliases"},
            ("work", "engagement"): {"outcomes"},
            ("work", "project"): {"outcomes"},
        }
        for key in optional_list_fields.get((domain, category), set()):
            value = payload.get(key)
            if value is None:
                continue
            if not isinstance(value, list) or any(not isinstance(item, str) or not item.strip() for item in value):
                payload.pop(key, None)
        lowered_text = text.lower()
        residence_markers = (" live in ", " moved to ", " based in ", " is my base")
        residence_value = None
        for key in ("city", "place", "value"):
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                residence_value = value.strip()
                break
        if domain == "biography" and residence_value and any(marker in f" {lowered_text} " for marker in residence_markers):
            normalized["category"] = "residence"
            normalized["subcategory"] = "city"
            normalized_payload = {"city": residence_value}
            if isinstance(payload.get("valid_from"), str) and payload["valid_from"].strip():
                normalized_payload["valid_from"] = payload["valid_from"].strip()
            normalized["payload"] = normalized_payload
            payload = normalized["payload"]
        if domain == "biography" and category == "city" and isinstance(payload.get("city"), str):
            normalized["category"] = "residence"
            normalized["subcategory"] = "city"
        if domain == "social_circle" and category == "relationship" and isinstance(payload.get("relation"), str):
            normalized["category"] = str(payload["relation"]).strip().lower()
        normalized["summary"] = self._normalize_provider_summary(
            subject_display=subject_display,
            domain=domain,
            category=str(normalized.get("category") or ""),
            payload=payload,
            summary=str(normalized.get("summary") or ""),
        )
        normalized["evidence"] = self._normalize_provider_evidence(
            evidence=candidate.get("evidence"),
            fallback_quote=text,
            message_id=message_id,
            source_segment_id=source_segment_id,
            session_id=session_id,
            fallback_message_ids=fallback_message_ids,
            fallback_source_segment_ids=fallback_source_segment_ids,
            fallback_session_ids=fallback_session_ids,
            chunk_kind=chunk_kind,
            attribution_method=attribution_method,
            attribution_confidence=attribution_confidence,
            source_type=source_type,
        )
        if attribution_method:
            payload["attribution_method"] = attribution_method
            payload["attribution_confidence"] = attribution_confidence
            payload["source_type"] = source_type
        review_reason_codes = {
            "speaker_unresolved",
            "relation_target_unresolved",
            "suspicious_identity_payload",
            "suspicious_residence_payload",
            "suspicious_work_payload",
        }
        review_reasons: list[str] = []
        existing_reason = normalized.get("reason")
        if isinstance(existing_reason, str):
            review_reasons.extend(
                part.strip()
                for part in existing_reason.split(",")
                if part.strip() in review_reason_codes
            )
        if person_id is None and "speaker_unresolved" not in review_reasons:
            review_reasons.append("speaker_unresolved")
        if (
            domain == "social_circle"
            and isinstance(payload.get("target_label"), str)
            and payload.get("target_label", "").strip()
            and payload.get("target_person_id") is None
            and "relation_target_unresolved" not in review_reasons
        ):
            review_reasons.append("relation_target_unresolved")
        for reason in self._candidate_quality_review_reasons(
            domain=domain,
            category=str(normalized.get("category") or ""),
            payload=payload,
        ):
            if reason not in review_reasons:
                review_reasons.append(reason)
        normalized["needs_review"] = bool(review_reasons)
        if review_reasons:
            normalized["reason"] = ",".join(review_reasons)
        return normalized

    def _candidate_quality_review_reasons(self, *, domain: str, category: str, payload: dict[str, Any]) -> list[str]:
        reasons: list[str] = []
        if domain == "biography" and category == "residence":
            city = str(payload.get("city") or "").strip()
            lowered = city.lower()
            if len(city.split()) > 4 or re.search(r"\b(?:and|prefer|work|moved|since|in\s+(?:19|20)\d{2})\b", lowered):
                reasons.append("suspicious_residence_payload")
        if domain == "biography" and category == "identity":
            name = str(payload.get("name") or "").strip()
            lowered = name.lower()
            if len(name.split()) > 4 or re.search(r"\b(?:moved|work|works|love|prefer|live|based)\b", lowered):
                reasons.append("suspicious_identity_payload")
        if domain == "work" and category == "employment":
            title = str(payload.get("title") or payload.get("role") or "").strip()
            org = str(payload.get("org") or "").strip()
            if re.search(r"\s+at\s+", title, re.IGNORECASE) and not org:
                reasons.append("suspicious_work_payload")
        return reasons

    def _normalize_provider_summary(
        self,
        *,
        subject_display: str,
        domain: str,
        category: str,
        payload: dict[str, Any],
        summary: str,
    ) -> str:
        if domain == "biography" and category == "residence" and isinstance(payload.get("city"), str):
            return f"{subject_display} lives in {payload['city'].strip()}."
        if domain == "biography" and category == "origin" and isinstance(payload.get("place"), str):
            return f"{subject_display} is from {payload['place'].strip()}."
        if domain == "preferences" and category == "preference" and isinstance(payload.get("value"), str):
            value = payload["value"].strip()
            polarity = str(payload.get("polarity") or "").strip().lower()
            if polarity == "dislike":
                return f"{subject_display} dislikes {value}."
            return f"{subject_display} likes {value}."
        if domain == "social_circle" and isinstance(payload.get("target_label"), str):
            target = payload["target_label"].strip()
            relation = str(payload.get("relation") or category).strip()
            if category == "relationship_event" and isinstance(payload.get("event"), str):
                return f"{subject_display} {payload['event'].strip()} {target}."
            return f"{subject_display} says {target} is their {relation}."
        if domain == "work" and category == "employment" and isinstance(payload.get("title"), str):
            if isinstance(payload.get("org"), str) and payload.get("org", "").strip():
                return f"{subject_display} works as {payload['title'].strip()} at {payload['org'].strip()}."
            return f"{subject_display} works as {payload['title'].strip()}."
        if domain == "work" and category == "role" and isinstance(payload.get("role"), str):
            return f"{subject_display} works as {payload['role'].strip()}."
        if domain == "work" and category == "org" and isinstance(payload.get("org"), str):
            return f"{subject_display} works at {payload['org'].strip()}."
        if domain == "experiences" and category == "event" and isinstance(payload.get("event"), str):
            return f"{subject_display} experienced {payload['event'].strip()}."
        return summary

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
        source_id: int | None = None,
        message_id: int | None = None,
        source_segment_id: int | None = None,
        session_id: int | None = None,
        occurred_at: str = "",
        include_style: bool = False,
        include_psychometrics: bool = False,
        chunk: ExtractionChunk | None = None,
        target_messages: list[MessageView] | None = None,
        attribution_method: str = "",
        attribution_confidence: float | None = None,
        source_type: str = "",
        strict_validation: bool = True,
    ) -> list[dict]:
        target_messages = target_messages or []
        metadata = {
            "text": text,
            "subject_key": subject_key,
            "subject_display": subject_display,
            "speaker_label": speaker_label,
            "person_id": person_id,
            "conn": conn,
            "workspace_id": workspace_id,
            "source_id": source_id,
            "message_id": message_id,
            "source_segment_id": source_segment_id,
            "session_id": session_id,
            "occurred_at": occurred_at,
            "include_style": include_style,
            "include_psychometrics": include_psychometrics,
            "chunk_id": chunk.chunk_id if chunk is not None else None,
            "chunk_kind": chunk.chunk_kind if chunk is not None else None,
            "chunk_messages": [message.model_dump(mode="json") for message in chunk.messages] if chunk is not None else [],
            "chunk_source_segment_ids": list(chunk.source_segment_ids) if chunk is not None else [],
            "chunk_overlap_prev": chunk.overlap_prev if chunk is not None else False,
            "chunk_overlap_next": chunk.overlap_next if chunk is not None else False,
            "target_message_ids": [message.message_id for message in target_messages],
            "attribution_method": attribution_method,
            "attribution_confidence": attribution_confidence,
            "source_type": source_type,
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
                session_id=session_id,
                occurred_at=occurred_at,
                include_style=include_style,
                include_psychometrics=include_psychometrics,
                chunk=chunk,
                target_message_ids=[message.message_id for message in target_messages],
            ),
            schema_name=EXTRACTION_SCHEMA_NAME,
            metadata=metadata,
        )
        content = response.content
        if isinstance(content, dict) and isinstance(content.get("items"), list):
            content = content["items"]
        if not isinstance(content, list):
            raise ValueError("LLM provider returned non-list candidate payload")
        usage_metadata = {
            **metadata,
            "schema_name": EXTRACTION_SCHEMA_NAME,
            "candidate_count": len(content),
            "candidate_domains": sorted(
                {
                    str(candidate.get("domain") or "")
                    for candidate in content
                    if isinstance(candidate, dict) and candidate.get("domain")
                }
            ),
        }
        self._record_usage(
            operation="complete_json",
            metadata=usage_metadata,
            usage=response.usage,
        )
        fallback_message_ids = [message.message_id for message in chunk.messages] if chunk is not None else []
        fallback_source_segment_ids = list(chunk.source_segment_ids) if chunk is not None else []
        fallback_session_ids = (
            sorted({int(message.session_id) for message in chunk.messages if message.session_id is not None})
            if chunk is not None
            else []
        )
        validated: list[dict] = []
        for candidate in content:
            try:
                if not isinstance(candidate, dict):
                    raise ValueError("LLM provider returned non-object candidate")
                validated.append(
                    validate_candidate(
                        self._normalize_provider_candidate(
                            candidate=candidate,
                            text=text,
                            subject_display=subject_display,
                            person_id=person_id,
                            message_id=message_id,
                            source_segment_id=source_segment_id,
                            session_id=session_id,
                            fallback_message_ids=fallback_message_ids,
                            fallback_source_segment_ids=fallback_source_segment_ids,
                            fallback_session_ids=fallback_session_ids,
                            chunk_kind=chunk.chunk_kind if chunk is not None else "conversation",
                            attribution_method=attribution_method,
                            attribution_confidence=attribution_confidence,
                            source_type=source_type,
                        )
                    )
                )
            except ValueError:
                if strict_validation:
                    raise
        return validated

    def _mock_extract_from_chunk(self, metadata: dict) -> list[dict]:
        target_person_id = metadata.get("person_id")
        target_speaker = str(metadata.get("speaker_label") or "")
        chunk = ExtractionChunk(
            chunk_id=int(metadata["chunk_id"]),
            chunk_kind="conversation",
            messages=[MessageView.model_validate(item) for item in metadata.get("chunk_messages", [])],
            text=str(metadata.get("text") or ""),
            source_segment_ids=[int(item) for item in metadata.get("chunk_source_segment_ids", [])],
            overlap_prev=bool(metadata.get("chunk_overlap_prev")),
            overlap_next=bool(metadata.get("chunk_overlap_next")),
        )
        candidates: list[dict] = []
        for message in chunk.messages:
            use_owner_fallback_message = (
                metadata.get("attribution_method") == "owner_first_person_fallback"
                and message.person_id is None
                and not message.speaker_label.strip()
            )
            if target_person_id is not None:
                if message.person_id != target_person_id and not use_owner_fallback_message:
                    continue
            elif message.speaker_label != target_speaker:
                continue
            effective_person_id = target_person_id if use_owner_fallback_message else message.person_id
            effective_speaker = target_speaker if use_owner_fallback_message else message.speaker_label
            candidates.extend(
                self._extract_from_text(
                    text=message.text,
                    subject_key=metadata["subject_key"],
                    subject_display=metadata["subject_display"],
                    speaker_label=effective_speaker,
                    person_id=effective_person_id,
                    conn=metadata["conn"],
                    workspace_id=metadata["workspace_id"],
                    message_id=message.message_id,
                    source_segment_id=message.source_segment_id,
                    session_id=message.session_id,
                    occurred_at=message.occurred_at,
                    include_style=metadata["include_style"],
                    include_psychometrics=metadata["include_psychometrics"],
                )
            )
        candidates.extend(
            self._chunk_window_candidate_payloads(
                chunk=chunk,
                target_person_id=target_person_id,
                target_speaker=target_speaker,
            )
        )
        return candidates

    def extract_candidates(self, *, source_text: str, person_hint: str | None = None) -> list[dict]:
        text = source_text.strip()
        if not text:
            return []
        resolved_subject_key = subject_key(None, person_hint or "", person_hint)
        resolved_subject_display = display_subject(person_hint or "", None)
        return self._extract_candidates_via_provider(
            text=text,
            subject_key=resolved_subject_key,
            subject_display=resolved_subject_display,
            speaker_label=person_hint or "",
            person_id=None,
            workspace_id=None,
            source_id=None,
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
        session_id: int | None = None,
        occurred_at: str = "",
        include_style: bool = False,
        include_psychometrics: bool = False,
    ) -> list[dict]:
        resolver = None
        if conn is not None and workspace_id is not None:
            resolver = lambda label: self._resolve_person_id(conn, workspace_id=workspace_id, label=label)
        return self.orchestrator.extract(
            ExtractionContext(
                text=text,
                subject_key=subject_key,
                subject_display=subject_display,
                speaker_label=speaker_label,
                person_id=person_id,
                conn=conn,
                workspace_id=workspace_id,
                message_id=message_id,
                source_segment_id=source_segment_id,
                session_id=session_id,
                occurred_at=occurred_at,
                resolve_person_id=resolver,
            ),
            include_style=include_style,
            include_psychometrics=include_psychometrics,
        )

    def _conversation_chunks(self, conn, *, conversation_id: int) -> list[ExtractionChunk]:
        message_rows = conn.execute(
            """
            SELECT
              cm.id AS message_id,
              cm.message_index,
              cm.speaker_label,
              cm.speaker_person_id AS person_id,
              cm.text,
              cm.occurred_at,
              cm.session_id,
              ss.id AS source_segment_id
            FROM conversation_messages cm
            LEFT JOIN source_segments ss
              ON ss.message_id = cm.id
             AND ss.segment_type = 'message'
            WHERE cm.conversation_id = ?
            ORDER BY cm.message_index ASC
            """,
            (conversation_id,),
        ).fetchall()
        messages_by_index = {
            int(row["message_index"]): MessageView(
                message_id=int(row["message_id"]),
                message_index=int(row["message_index"]),
                speaker_label=row["speaker_label"] or "",
                person_id=int(row["person_id"]) if row["person_id"] is not None else None,
                text=row["text"] or "",
                occurred_at=row["occurred_at"] or "",
                source_segment_id=int(row["source_segment_id"]) if row["source_segment_id"] is not None else None,
                session_id=int(row["session_id"]) if row["session_id"] is not None else None,
            )
            for row in message_rows
        }
        chunk_rows = conn.execute(
            """
            SELECT id, text, locator_json
            FROM conversation_chunks
            WHERE conversation_id = ?
            ORDER BY chunk_index ASC
            """,
            (conversation_id,),
        ).fetchall()
        overlap_by_chunk: list[bool] = []
        chunk_indexes: list[list[int]] = []
        for row in chunk_rows:
            locator = json.loads(row["locator_json"] or "{}")
            indexes = [int(index) for index in locator.get("message_indexes", [])]
            chunk_indexes.append(indexes)
            overlap_by_chunk.append(bool(locator.get("overlap_message_indexes")))

        chunks: list[ExtractionChunk] = []
        for position, row in enumerate(chunk_rows):
            indexes = chunk_indexes[position]
            messages = [messages_by_index[index] for index in indexes if index in messages_by_index]
            source_segment_ids = [
                int(message.source_segment_id)
                for message in messages
                if message.source_segment_id is not None
            ]
            chunks.append(
                ExtractionChunk(
                    chunk_id=int(row["id"]),
                    chunk_kind="conversation",
                    messages=messages,
                    text=row["text"] or "",
                    source_segment_ids=source_segment_ids,
                    overlap_prev=overlap_by_chunk[position],
                    overlap_next=position + 1 < len(overlap_by_chunk) and overlap_by_chunk[position + 1],
                )
            )
        return chunks

    def _chunk_window_candidate_payloads(
        self,
        *,
        chunk: ExtractionChunk,
        target_person_id: int | None,
        target_speaker: str,
    ) -> list[dict]:
        candidates: list[dict] = []
        moved_there_re = re.compile(r"\bi\s+moved\s+there(?:\s+in\s+((?:19|20)\d{2}))?\b", re.IGNORECASE)
        city_confirm_re = re.compile(
            r"\b(?:you\s+mean\s+(?P<city_you_mean>[A-Z][A-Za-z0-9&.\-]*(?:\s+[A-Z][A-Za-z0-9&.\-]*)?)|(?P<city_right>[A-Z][A-Za-z0-9&.\-]*(?:\s+[A-Z][A-Za-z0-9&.\-]*)?),?\s+right)\??\s*$",
            re.IGNORECASE,
        )
        yes_re = re.compile(r"^\s*(?:yes|yeah|yep|correct|right|that's right)\b", re.IGNORECASE)
        messages = chunk.messages
        for index, message in enumerate(messages[:-2]):
            moved_match = moved_there_re.search(message.text)
            if moved_match is None:
                continue
            if target_person_id is not None:
                if message.person_id != target_person_id:
                    continue
            elif message.speaker_label != target_speaker:
                continue
            confirmation = messages[index + 1]
            yes_message = messages[index + 2]
            city_match = city_confirm_re.search(confirmation.text)
            if city_match is None or yes_re.search(yes_message.text) is None:
                continue
            if yes_message.person_id != message.person_id or yes_message.speaker_label != message.speaker_label:
                continue
            city = (city_match.group("city_you_mean") or city_match.group("city_right") or "").strip()
            if not city:
                continue
            valid_from = moved_match.group(1) or ""
            evidence_messages = [message, confirmation, yes_message]
            evidence = [
                {
                    "quote": "\n".join(
                        f"{item.speaker_label}: {item.text}" if item.speaker_label else item.text
                        for item in evidence_messages
                    ),
                    "message_ids": [str(item.message_id) for item in evidence_messages],
                    "source_segment_ids": [
                        int(item.source_segment_id)
                        for item in evidence_messages
                        if item.source_segment_id is not None
                    ],
                    "session_ids": [
                        int(item.session_id)
                        for item in evidence_messages
                        if item.session_id is not None
                    ],
                    "chunk_kind": "conversation",
                }
            ]
            review_reasons = ["speaker_unresolved"] if message.person_id is None else []
            payload = {"city": city}
            if valid_from:
                payload["valid_from"] = valid_from
            candidates.append(
                {
                    "domain": "biography",
                    "category": "residence",
                    "subcategory": "",
                    "canonical_key": f"{subject_key(message.person_id, message.speaker_label)}:biography:residence:{slugify(city)}",
                    "payload": payload,
                    "summary": f"{display_subject(message.speaker_label, message.person_id)} lives in {city}.",
                    "confidence": 0.86 if message.person_id is not None else 0.6,
                    "reason": ",".join(review_reasons),
                    "needs_review": bool(review_reasons),
                    "evidence": evidence,
                }
            )
        return candidates

    def _owner_first_person_fallback_allowed(self, chunk: ExtractionChunk) -> bool:
        if not chunk.messages:
            return False
        if any(message.person_id is not None or message.speaker_label.strip() for message in chunk.messages):
            return False
        text = chunk.text.strip()
        return bool(FIRST_PERSON_RE.search(text)) and THIRD_PERSON_AMBIGUITY_RE.search(text) is None

    def extract_candidates_from_conversation(
        self,
        conn,
        *,
        conversation_id: int,
        include_style: bool = False,
        include_psychometrics: bool = False,
        owner_person_id: int | None = None,
        owner_display_name: str = "",
        attribution_policy: str = "strict_speaker_only",
    ) -> list[dict]:
        meta_row = conn.execute(
            """
            SELECT c.id AS conversation_id, c.workspace_id, c.source_id, s.source_type
            FROM conversations c
            JOIN sources s
              ON s.id = c.source_id
            WHERE c.id = ?
            """,
            (conversation_id,),
        ).fetchone()
        if meta_row is None:
            return []
        chunks = self._conversation_chunks(conn, conversation_id=conversation_id)
        candidates: list[dict] = []
        for chunk in chunks:
            targets: list[tuple[int | None, str, list[MessageView]]] = []
            seen_targets: set[tuple[int | None, str]] = set()
            for message in chunk.messages:
                target_key = (message.person_id, message.speaker_label)
                if target_key not in seen_targets:
                    seen_targets.add(target_key)
                    targets.append((message.person_id, message.speaker_label, []))
                for index, existing in enumerate(targets):
                    if (existing[0], existing[1]) == target_key:
                        targets[index] = (existing[0], existing[1], [*existing[2], message])
                        break
            for person_id, speaker_label, target_messages in targets:
                if not target_messages:
                    continue
                primary = target_messages[0]
                use_message_fallback = len(chunk.messages) == 1
                provider_text = primary.text if use_message_fallback else chunk.text
                provider_chunk = None if use_message_fallback else chunk
                provider_target_messages = [] if use_message_fallback else target_messages
                effective_person_id = person_id
                effective_speaker_label = speaker_label
                attribution_method = ""
                attribution_confidence = None
                if (
                    attribution_policy == "owner_first_person_fallback"
                    and person_id is None
                    and not speaker_label.strip()
                    and owner_person_id is not None
                    and self._owner_first_person_fallback_allowed(chunk)
                ):
                    effective_person_id = owner_person_id
                    effective_speaker_label = owner_display_name
                    attribution_method = "owner_first_person_fallback"
                    attribution_confidence = 0.96
                extracted = self._extract_candidates_via_provider(
                    text=provider_text,
                    subject_key=subject_key(effective_person_id, effective_speaker_label),
                    subject_display=display_subject(effective_speaker_label, effective_person_id),
                    speaker_label=effective_speaker_label,
                    person_id=effective_person_id,
                    conn=conn,
                    workspace_id=int(meta_row["workspace_id"]),
                    source_id=int(meta_row["source_id"]),
                    message_id=primary.message_id if use_message_fallback else None,
                    source_segment_id=primary.source_segment_id if use_message_fallback else None,
                    session_id=primary.session_id,
                    occurred_at=primary.occurred_at,
                    include_style=include_style,
                    include_psychometrics=include_psychometrics,
                    chunk=provider_chunk,
                    target_messages=provider_target_messages,
                    attribution_method=attribution_method,
                    attribution_confidence=attribution_confidence,
                    source_type=str(meta_row["source_type"] or ""),
                    strict_validation=False,
                )
                for candidate in extracted:
                    candidates.append(
                        {
                            "conversation_id": int(meta_row["conversation_id"]),
                            "source_id": int(meta_row["source_id"]),
                            "chunk_kind": "conversation",
                            "chunk_id": chunk.chunk_id,
                            "session_id": primary.session_id,
                            "person_id": effective_person_id,
                            "speaker_label": effective_speaker_label,
                            "text": provider_text,
                            "occurred_at": primary.occurred_at,
                            "message_id": primary.message_id,
                            **candidate,
                        }
                    )
        return candidates

    def _source_chunks(self, conn, *, source_id: int) -> list[ExtractionChunk]:
        rows = conn.execute(
            """
            SELECT
              sc.id AS chunk_id,
              sc.text,
              sc.locator_json,
              ss.id AS source_segment_id
            FROM source_chunks sc
            LEFT JOIN source_segments ss
              ON ss.chunk_id = sc.id
             AND ss.segment_type = 'source_chunk'
            WHERE sc.source_id = ?
            ORDER BY sc.chunk_index ASC
            """,
            (source_id,),
        ).fetchall()
        chunks: list[ExtractionChunk] = []
        for row in rows:
            locator = json.loads(row["locator_json"] or "{}")
            token_window = locator.get("token_window") if isinstance(locator, dict) else {}
            if not isinstance(token_window, dict):
                token_window = {}
            source_segment_ids = []
            if row["source_segment_id"] is not None:
                source_segment_ids.append(int(row["source_segment_id"]))
            chunks.append(
                ExtractionChunk(
                    chunk_id=int(row["chunk_id"]),
                    chunk_kind="source",
                    text=row["text"] or "",
                    source_segment_ids=source_segment_ids,
                    overlap_prev=bool(token_window.get("overlap_prev")),
                    overlap_next=bool(token_window.get("overlap_next")),
                )
            )
        return chunks

    def extract_candidates_from_source(
        self,
        conn,
        *,
        source_id: int,
        person_id: int | None = None,
        speaker_label: str = "",
        attribution_method: str = "",
        attribution_confidence: float | None = None,
        include_style: bool = False,
        include_psychometrics: bool = False,
    ) -> list[dict]:
        source_row = conn.execute(
            "SELECT id, workspace_id, source_type FROM sources WHERE id = ?",
            (source_id,),
        ).fetchone()
        if source_row is None:
            return []
        candidates: list[dict] = []
        for chunk in self._source_chunks(conn, source_id=source_id):
            source_segment_id = chunk.source_segment_ids[0] if chunk.source_segment_ids else None
            extracted = self._extract_candidates_via_provider(
                text=chunk.text,
                subject_key=subject_key(person_id, speaker_label),
                subject_display=display_subject(speaker_label, person_id),
                speaker_label=speaker_label,
                person_id=person_id,
                conn=conn,
                workspace_id=int(source_row["workspace_id"]),
                source_id=int(source_row["id"]),
                source_segment_id=source_segment_id,
                include_style=include_style,
                include_psychometrics=include_psychometrics,
                chunk=chunk,
                target_messages=[],
                attribution_method=attribution_method,
                attribution_confidence=attribution_confidence,
                source_type=str(source_row["source_type"] or ""),
                strict_validation=False,
            )
            for candidate in extracted:
                candidates.append(
                    {
                        "conversation_id": None,
                        "source_id": int(source_row["id"]),
                        "chunk_kind": "source",
                        "chunk_id": chunk.chunk_id,
                        "session_id": None,
                        "person_id": person_id,
                        "speaker_label": speaker_label,
                        "text": chunk.text,
                        "occurred_at": "",
                        "message_id": None,
                        **candidate,
                    }
                )
        return candidates

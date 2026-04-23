from __future__ import annotations

import json
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
    ) -> str:
        return json.dumps(
            build_prompt_payload(
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
            ),
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
        if schema_name != EXTRACTION_SCHEMA_NAME:
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
                "workspace_id": metadata.get("workspace_id"),
                "has_person_id": metadata.get("person_id") is not None,
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
    ) -> dict[str, Any]:
        return {
            "quote": quote.strip(),
            "message_ids": [str(message_id)] if message_id is not None else [],
            "source_segment_ids": [int(source_segment_id)] if source_segment_id is not None else [],
            "session_ids": [int(session_id)] if session_id is not None else [],
            "chunk_kind": "conversation",
        }

    def _normalize_provider_evidence(
        self,
        *,
        evidence: Any,
        fallback_quote: str,
        message_id: int | None,
        source_segment_id: int | None,
        session_id: int | None,
    ) -> list[dict[str, Any]]:
        default_item = self._default_evidence_item(
            quote=fallback_quote,
            message_id=message_id,
            source_segment_id=source_segment_id,
            session_id=session_id,
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
                        )
                    )
                    continue
                if not isinstance(item, dict):
                    continue
                quote = item.get("quote")
                if not isinstance(quote, str) or not quote.strip():
                    quote = fallback_quote
                normalized.append(
                    {
                        "quote": quote.strip(),
                        "message_ids": item.get("message_ids")
                        if isinstance(item.get("message_ids"), list)
                        else list(default_item["message_ids"]),
                        "source_segment_ids": item.get("source_segment_ids")
                        if isinstance(item.get("source_segment_ids"), list)
                        else list(default_item["source_segment_ids"]),
                        "session_ids": item.get("session_ids")
                        if isinstance(item.get("session_ids"), list)
                        else list(default_item["session_ids"]),
                        "chunk_kind": item.get("chunk_kind")
                        if isinstance(item.get("chunk_kind"), str) and item.get("chunk_kind", "").strip()
                        else default_item["chunk_kind"],
                    }
                )
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
    ) -> dict[str, Any]:
        normalized = dict(candidate)
        domain = str(normalized.get("domain") or "")
        payload = normalized.get("payload")
        if not isinstance(payload, dict):
            payload = {}
            normalized["payload"] = payload
        category = str(normalized.get("category") or "")
        optional_blank_string_fields = {
            ("preferences", "preference"): {"strength", "reason"},
            ("social_circle", "relationship_event"): {"context"},
            ("work", "employment"): set(),
            ("work", "role"): set(),
            ("work", "org"): set(),
            ("work", "project"): set(),
            ("work", "skill"): set(),
            ("work", "tool"): set(),
            ("experiences", "event"): {"summary", "temporal_anchor", "outcome", "valence"},
        }
        removable_fields = optional_blank_string_fields.get((domain, category), set())
        for key in list(payload.keys()):
            value = payload.get(key)
            if key in removable_fields and (not isinstance(value, str) or not value.strip()):
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
            normalized["payload"] = {"city": residence_value}
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
        )
        review_reason_codes = {"speaker_unresolved", "relation_target_unresolved"}
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
        normalized["needs_review"] = bool(review_reasons)
        if review_reasons:
            normalized["reason"] = ",".join(review_reasons)
        return normalized

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
        message_id: int | None = None,
        source_segment_id: int | None = None,
        session_id: int | None = None,
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
            "session_id": session_id,
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
                session_id=session_id,
                occurred_at=occurred_at,
                include_style=include_style,
                include_psychometrics=include_psychometrics,
            ),
            schema_name=EXTRACTION_SCHEMA_NAME,
            metadata=metadata,
        )
        self._record_usage(
            operation="complete_json",
            metadata={**metadata, "schema_name": EXTRACTION_SCHEMA_NAME},
            usage=response.usage,
        )
        content = response.content
        if isinstance(content, dict) and isinstance(content.get("items"), list):
            content = content["items"]
        if not isinstance(content, list):
            raise ValueError("LLM provider returned non-list candidate payload")
        return [
            validate_candidate(
                self._normalize_provider_candidate(
                    candidate=candidate,
                    text=text,
                    subject_display=subject_display,
                    person_id=person_id,
                    message_id=message_id,
                    source_segment_id=source_segment_id,
                    session_id=session_id,
                )
            )
            for candidate in content
        ]

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

    def extract_candidates_from_conversation(self, conn, *, conversation_id: int, include_style: bool = False, include_psychometrics: bool = False) -> list[dict]:
        rows = conn.execute(
            """
            SELECT
              c.id AS conversation_id,
              c.workspace_id,
              c.source_id,
              cm.session_id,
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
                subject_key=subject_key(person_id, speaker_label),
                subject_display=display_subject(speaker_label, person_id),
                speaker_label=speaker_label,
                person_id=person_id,
                conn=conn,
                workspace_id=int(item["workspace_id"]),
                message_id=int(item["message_id"]),
                source_segment_id=int(item["source_segment_id"]) if item.get("source_segment_id") is not None else None,
                session_id=int(item["session_id"]) if item.get("session_id") is not None else None,
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
                        "session_id": int(item["session_id"]) if item.get("session_id") is not None else None,
                        "person_id": person_id,
                        "speaker_label": speaker_label,
                        "text": item.get("text") or "",
                        "occurred_at": item.get("occurred_at") or "",
                        "message_id": int(item["message_id"]),
                        **candidate,
                    }
                )
        return candidates

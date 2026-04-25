from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone

from memco.llm import build_llm_provider
from memco.models.conversation import ConversationImportResult
from memco.repositories.conversation_repository import ConversationRepository
from memco.repositories.fact_repository import FactRepository
from memco.utils import slugify


SPEAKER_LINE_RE = re.compile(
    r"^(?:(?P<timestamp>\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}Z?)\s+)?(?P<speaker>[^:\n]{1,120}):\s*(?P<text>.+)$"
)


def _normalize_speaker_key(label: str) -> str:
    return " ".join(label.strip().lower().split())


def _render_message_line(message: dict) -> str:
    header = []
    if message.get("occurred_at"):
        header.append(message["occurred_at"])
    if message.get("speaker_label"):
        header.append(message["speaker_label"])
    prefix = " ".join(header).strip()
    return f"{prefix}: {message['text']}" if prefix else message["text"]


def _parse_occurred_at(value: str) -> datetime | None:
    normalized = value.strip()
    if not normalized:
        return None
    if normalized.endswith("Z"):
        normalized = normalized[:-1] + "+00:00"
    normalized = normalized.replace(" ", "T")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _explicit_session_key(message: dict) -> str:
    meta = message.get("meta") or {}
    raw = (
        message.get("session_uid")
        or meta.get("session_uid")
        or meta.get("session_id")
        or meta.get("session")
        or ""
    )
    return str(raw).strip()


class ConversationIngestService:
    def __init__(
        self,
        conversation_repository: ConversationRepository | None = None,
        fact_repository: FactRepository | None = None,
    ) -> None:
        self.conversation_repository = conversation_repository or ConversationRepository()
        self.fact_repository = fact_repository or FactRepository()

    def _parse_messages(self, parsed_text: str, source_type: str, source_meta: dict | None = None) -> list[dict]:
        meta = source_meta or {}
        if source_type == "json":
            data = json.loads(parsed_text)
            if isinstance(data, dict):
                if isinstance(data.get("messages"), list):
                    data = data["messages"]
                else:
                    data = [data]
            if not isinstance(data, list):
                raise ValueError("Unsupported JSON conversation format")
            messages: list[dict] = []
            for item in data:
                if not isinstance(item, dict):
                    continue
                item_meta = item.get("meta")
                meta = dict(item_meta) if isinstance(item_meta, dict) else {}
                explicit_session = (
                    item.get("session_uid")
                    or item.get("session_id")
                    or item.get("session")
                    or meta.get("session_uid")
                    or meta.get("session_id")
                    or meta.get("session")
                    or ""
                )
                if explicit_session:
                    meta["session_uid"] = str(explicit_session).strip()
                speaker_label = str(
                    item.get("speaker")
                    or item.get("author")
                    or item.get("from")
                    or item.get("role")
                    or ""
                )
                messages.append(
                    {
                        "role": str(item.get("role") or "unknown"),
                        "speaker_label": speaker_label,
                        "occurred_at": str(item.get("timestamp") or item.get("occurred_at") or item.get("date") or ""),
                        "text": str(item.get("text") or item.get("content") or item.get("message") or "").strip(),
                        "meta": meta,
                    }
                )
            return [message for message in messages if message["text"]]

        if source_type in {"email", "whatsapp", "telegram"}:
            raw_messages = meta.get("messages") if isinstance(meta.get("messages"), list) else []
            messages: list[dict] = []
            for item in raw_messages:
                if not isinstance(item, dict):
                    continue
                item_meta = item.get("meta")
                message_meta = dict(item_meta) if isinstance(item_meta, dict) else {}
                messages.append(
                    {
                        "role": str(item.get("role") or source_type),
                        "speaker_label": str(item.get("speaker") or item.get("from") or item.get("author") or ""),
                        "occurred_at": str(item.get("timestamp") or item.get("date") or ""),
                        "text": str(item.get("text") or item.get("body") or "").strip(),
                        "meta": message_meta,
                    }
                )
            if messages:
                return [message for message in messages if message["text"]]

        messages = []
        for line in parsed_text.splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            match = SPEAKER_LINE_RE.match(stripped)
            if match:
                messages.append(
                    {
                        "role": "unknown",
                        "speaker_label": match.group("speaker").strip(),
                        "occurred_at": (match.group("timestamp") or "").strip(),
                        "text": match.group("text").strip(),
                        "meta": {},
                    }
                )
            elif messages:
                messages[-1]["text"] = f"{messages[-1]['text']}\n{stripped}".strip()
            else:
                messages.append(
                    {
                        "role": "unknown",
                        "speaker_label": "",
                        "occurred_at": "",
                        "text": stripped,
                        "meta": {},
                    }
                )
        return messages

    def _resolve_speakers(self, conn, *, workspace_slug: str, messages: list[dict]) -> list[dict]:
        resolved: list[dict] = []
        seen: dict[str, dict] = {}
        workspace_id = self.fact_repository.ensure_workspace(conn, workspace_slug)
        for message in messages:
            label = message.get("speaker_label", "")
            speaker_key = _normalize_speaker_key(label)
            person_id = None
            resolution_method = "unresolved"
            confidence = 0.0
            if speaker_key:
                row = conn.execute(
                    """
                    SELECT person_id
                    FROM person_aliases
                    WHERE workspace_id = ? AND normalized_alias = ? AND alias_type = 'name'
                    """,
                    (workspace_id, speaker_key),
                ).fetchone()
                if row is not None:
                    person_id = int(row["person_id"])
                    resolution_method = "alias_exact"
                    confidence = 1.0
            resolved_message = {
                **message,
                "speaker_key": speaker_key,
                "speaker_person_id": person_id,
            }
            resolved.append(resolved_message)
            if speaker_key and speaker_key not in seen:
                seen[speaker_key] = {
                    "speaker_key": speaker_key,
                    "raw_label": label,
                    "person_id": person_id,
                    "resolution_method": resolution_method,
                    "confidence": confidence,
                }
        return resolved, list(seen.values())

    def _assign_sessions(self, messages: list[dict], *, gap_minutes: int) -> tuple[list[dict], list[dict]]:
        if not messages:
            return [], []
        assigned: list[dict] = []
        sessions: list[dict] = []
        current_session_index = -1
        current_explicit_key = ""
        previous_occurred_at: datetime | None = None
        gap_threshold = timedelta(minutes=max(1, gap_minutes))

        def start_session(*, detection_method: str, explicit_key: str = "") -> None:
            nonlocal current_session_index, current_explicit_key
            current_session_index += 1
            current_explicit_key = explicit_key
            sessions.append(
                {
                    "session_index": current_session_index,
                    "session_uid": f"session-{current_session_index + 1:04d}",
                    "started_at": "",
                    "ended_at": "",
                    "detection_method": detection_method,
                    "meta": {"external_session_key": explicit_key} if explicit_key else {},
                }
            )

        for index, message in enumerate(messages):
            explicit_key = _explicit_session_key(message)
            normalized_explicit = slugify(explicit_key) if explicit_key else ""
            occurred_at = _parse_occurred_at(message.get("occurred_at", ""))
            if current_session_index < 0:
                start_session(detection_method="explicit" if normalized_explicit else "single", explicit_key=normalized_explicit)
            elif normalized_explicit and normalized_explicit != current_explicit_key:
                start_session(detection_method="explicit", explicit_key=normalized_explicit)
            elif not normalized_explicit and previous_occurred_at is not None and occurred_at is not None:
                if occurred_at - previous_occurred_at > gap_threshold:
                    start_session(detection_method="gap")
            session = sessions[current_session_index]
            if occurred_at is not None:
                occurred_text = occurred_at.replace(microsecond=0).isoformat().replace("+00:00", "Z")
                if not session["started_at"]:
                    session["started_at"] = occurred_text
                session["ended_at"] = occurred_text
                previous_occurred_at = occurred_at
            session_meta = dict(message.get("meta") or {})
            if explicit_key:
                session_meta["session_uid"] = explicit_key
            assigned.append(
                {
                    **message,
                    "meta": session_meta,
                    "session_index": current_session_index,
                    "session_uid": session["session_uid"],
                }
            )
            session["meta"]["message_indexes"] = [
                *(session["meta"].get("message_indexes") or []),
                index,
            ]
        return assigned, sessions

    def _build_chunks(
        self,
        messages: list[dict],
        *,
        max_tokens_per_chunk: int,
        overlap_tokens: int,
        count_tokens,
    ) -> list[dict]:
        if not messages:
            return []
        prepared = [
            {
                **message,
                "message_index": index,
                "line": _render_message_line(message),
            }
            for index, message in enumerate(messages)
        ]
        budget = max(1, int(max_tokens_per_chunk))
        overlap_budget = max(0, int(overlap_tokens))
        for message in prepared:
            message["message_token_count"] = max(1, int(count_tokens(text=message["line"])))
            if int(message["message_token_count"]) > budget:
                raise ValueError(
                    "Conversation message exceeds max_tokens_per_chunk; "
                    "increase ingest.max_tokens_per_chunk or pre-split the source."
                )

        chunks: list[dict] = []
        position = 0
        overlap_from_indexes: list[int] = []

        while position < len(prepared):
            start = position
            session_id = prepared[start].get("session_id")
            session_uid = prepared[start].get("session_uid", "")
            token_count = 0
            end = start - 1
            cursor = start

            while cursor < len(prepared):
                message = prepared[cursor]
                if message.get("session_id") != session_id:
                    break
                message_tokens = int(message["message_token_count"])
                if end >= start and token_count + message_tokens > budget:
                    break
                token_count += message_tokens
                end = cursor
                cursor += 1
                if token_count >= budget:
                    break

            if end < start:
                end = start
                cursor = start + 1
                token_count = int(prepared[start]["message_token_count"])

            chunk_messages = prepared[start : end + 1]
            chunks.append(
                {
                    "session_id": session_id,
                    "session_uid": session_uid,
                    "start_message_index": int(chunk_messages[0]["message_index"]),
                    "end_message_index": int(chunk_messages[-1]["message_index"]),
                    "text": "\n".join(item["line"] for item in chunk_messages),
                    "token_count": token_count,
                    "locator": {
                        "message_indexes": [int(item["message_index"]) for item in chunk_messages],
                        "overlap_message_indexes": overlap_from_indexes,
                        "message_token_counts": {
                            str(item["message_index"]): int(item["message_token_count"])
                            for item in chunk_messages
                        },
                        "token_budget": budget,
                        "overlap_tokens": overlap_budget,
                        "session_id": session_id,
                        "session_uid": session_uid,
                    },
                }
            )

            next_position = cursor
            next_overlap_from_indexes: list[int] = []
            if next_position < len(prepared) and prepared[next_position].get("session_id") == session_id and overlap_budget > 0:
                overlap_start = next_position
                overlap_used = 0
                for index in range(end, start, -1):
                    message_tokens = int(prepared[index]["message_token_count"])
                    if overlap_used + message_tokens > overlap_budget:
                        break
                    overlap_used += message_tokens
                    overlap_start = index
                if overlap_start < next_position:
                    next_overlap_from_indexes = [
                        int(item["message_index"]) for item in prepared[overlap_start:next_position]
                    ]
                    next_position = overlap_start

            position = next_position
            overlap_from_indexes = next_overlap_from_indexes

        return chunks

    def list_speakers(self, conn, *, conversation_id: int) -> list[dict]:
        return self.conversation_repository.list_speaker_map(
            conn,
            conversation_id=conversation_id,
        )

    def resolve_speaker(
        self,
        conn,
        *,
        workspace_slug: str,
        conversation_id: int,
        speaker_key: str,
        person_id: int | None = None,
        person_slug: str | None = None,
        create_person_display_name: str | None = None,
        create_person_slug: str | None = None,
    ) -> dict:
        target_person_id = person_id
        if target_person_id is None and person_slug:
            target_person_id = self.fact_repository.resolve_person_id(
                conn,
                workspace_slug=workspace_slug,
                person_slug=person_slug,
            )
        if target_person_id is None and create_person_display_name:
            person = self.fact_repository.upsert_person(
                conn,
                workspace_slug=workspace_slug,
                display_name=create_person_display_name,
                slug=create_person_slug or slugify(create_person_display_name),
                person_type="human",
                aliases=[create_person_display_name],
            )
            target_person_id = int(person["id"])
        if target_person_id is None:
            raise ValueError("person_id, person_slug, or create_person_display_name is required")
        existing = self.conversation_repository.list_speaker_map(conn, conversation_id=conversation_id)
        matching = next((item for item in existing if item["speaker_key"] == speaker_key), None)
        raw_label = matching["raw_label"] if matching is not None else speaker_key
        return self.conversation_repository.resolve_speaker(
            conn,
            conversation_id=conversation_id,
            speaker_key=speaker_key,
            person_id=int(target_person_id),
            raw_label=raw_label,
        )

    def import_conversation(self, settings, conn, *, workspace_slug: str, source_id: int, conversation_uid: str = "main", title: str = "") -> ConversationImportResult:
        source_row = conn.execute("SELECT * FROM sources WHERE id = ?", (source_id,)).fetchone()
        if source_row is None:
            raise ValueError("Unknown source")
        source = dict(source_row)
        source_meta = json.loads(source.get("meta_json") or "{}")
        messages = self._parse_messages(source["parsed_text"], source["source_type"], source_meta)
        session_messages, session_specs = self._assign_sessions(
            messages,
            gap_minutes=settings.ingest.session_gap_minutes,
        )
        started_at = next((message["occurred_at"] for message in session_messages if message.get("occurred_at")), "")
        ended_at = next((message["occurred_at"] for message in reversed(session_messages) if message.get("occurred_at")), "")
        conversation_id = self.conversation_repository.upsert_conversation(
            conn,
            workspace_slug=workspace_slug,
            source_id=source_id,
            conversation_uid=conversation_uid,
            title=title or source.get("title", ""),
            started_at=started_at,
            ended_at=ended_at,
        )
        resolved_messages, speaker_map = self._resolve_speakers(
            conn,
            workspace_slug=workspace_slug,
            messages=session_messages,
        )
        token_counter = build_llm_provider(settings).count_tokens
        self.conversation_repository.prepare_conversation_replace(conn, conversation_id=conversation_id)
        session_rows = self.conversation_repository.replace_sessions(
            conn,
            conversation_id=conversation_id,
            source_id=source_id,
            sessions=session_specs,
        )
        resolved_messages = [
            {
                **message,
                "session_id": session_rows[int(message["session_index"])]["id"],
            }
            for message in resolved_messages
        ]
        self.conversation_repository.replace_messages(
            conn,
            conversation_id=conversation_id,
            messages=resolved_messages,
        )
        self.conversation_repository.upsert_speaker_map(
            conn,
            conversation_id=conversation_id,
            mappings=speaker_map,
        )
        chunks = self._build_chunks(
            resolved_messages,
            max_tokens_per_chunk=settings.ingest.max_tokens_per_chunk,
            overlap_tokens=settings.ingest.overlap_tokens,
            count_tokens=token_counter,
        )
        self.conversation_repository.replace_chunks(
            conn,
            conversation_id=conversation_id,
            source_id=source_id,
            chunks=chunks,
        )
        unresolved = sorted(
            {
                mapping["raw_label"]
                for mapping in speaker_map
                if mapping["person_id"] is None and mapping["raw_label"]
            }
        )
        return ConversationImportResult(
            conversation_id=conversation_id,
            source_id=source_id,
            session_count=len(session_rows),
            message_count=len(resolved_messages),
            chunk_count=len(chunks),
            unresolved_speakers=unresolved,
        )

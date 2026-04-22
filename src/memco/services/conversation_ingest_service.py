from __future__ import annotations

import json
import re

from memco.models.conversation import ConversationImportResult
from memco.repositories.conversation_repository import ConversationRepository
from memco.repositories.fact_repository import FactRepository
from memco.utils import slugify


SPEAKER_LINE_RE = re.compile(
    r"^(?:(?P<timestamp>\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}Z?)\s+)?(?P<speaker>[^:\n]{1,120}):\s*(?P<text>.+)$"
)


def _normalize_speaker_key(label: str) -> str:
    return " ".join(label.strip().lower().split())


class ConversationIngestService:
    def __init__(
        self,
        conversation_repository: ConversationRepository | None = None,
        fact_repository: FactRepository | None = None,
    ) -> None:
        self.conversation_repository = conversation_repository or ConversationRepository()
        self.fact_repository = fact_repository or FactRepository()

    def _parse_messages(self, parsed_text: str, source_type: str) -> list[dict]:
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
                        "meta": {},
                    }
                )
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

    def _build_chunks(self, messages: list[dict], max_chars: int) -> list[dict]:
        chunks: list[dict] = []
        current_lines: list[str] = []
        current_len = 0
        start_index = 0
        last_index = 0
        for index, message in enumerate(messages):
            header = []
            if message.get("occurred_at"):
                header.append(message["occurred_at"])
            if message.get("speaker_label"):
                header.append(message["speaker_label"])
            prefix = " ".join(header).strip()
            line = f"{prefix}: {message['text']}" if prefix else message["text"]
            candidate_len = current_len + len(line) + (1 if current_lines else 0)
            if current_lines and candidate_len > max_chars:
                text = "\n".join(current_lines)
                chunks.append(
                    {
                        "start_message_index": start_index,
                        "end_message_index": last_index,
                        "text": text,
                        "token_count": max(1, len(text.split())),
                        "locator": {
                            "message_indexes": list(range(start_index, last_index + 1)),
                        },
                    }
                )
                current_lines = [line]
                current_len = len(line)
                start_index = index
                last_index = index
                continue
            if not current_lines:
                start_index = index
            current_lines.append(line)
            current_len = candidate_len
            last_index = index
        if current_lines:
            text = "\n".join(current_lines)
            chunks.append(
                {
                    "start_message_index": start_index,
                    "end_message_index": last_index,
                    "text": text,
                    "token_count": max(1, len(text.split())),
                    "locator": {
                        "message_indexes": list(range(start_index, last_index + 1)),
                    },
                }
            )
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
        messages = self._parse_messages(source["parsed_text"], source["source_type"])
        started_at = next((message["occurred_at"] for message in messages if message.get("occurred_at")), "")
        ended_at = next((message["occurred_at"] for message in reversed(messages) if message.get("occurred_at")), "")
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
            messages=messages,
        )
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
        chunks = self._build_chunks(resolved_messages, settings.ingest.max_chunk_chars)
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
            message_count=len(resolved_messages),
            chunk_count=len(chunks),
            unresolved_speakers=unresolved,
        )

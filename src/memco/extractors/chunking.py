from __future__ import annotations

from collections.abc import Iterable

from memco.llm_usage import estimate_token_count
from memco.models.conversation import ExtractionChunk, MessageView


def chunk_messages(
    messages: Iterable[MessageView],
    *,
    max_chunk_tokens: int = 3000,
    chunk_overlap_tokens: int = 300,
) -> list[ExtractionChunk]:
    ordered = list(messages)
    if not ordered:
        return []
    chunks: list[list[MessageView]] = []
    current: list[MessageView] = []
    current_tokens = 0
    index = 0
    while index < len(ordered):
        message = ordered[index]
        message_tokens = _message_tokens(message)
        if current and current_tokens + message_tokens > max_chunk_tokens:
            chunks.append(current)
            overlap = _overlap_tail(current, chunk_overlap_tokens)
            if len(overlap) == len(current):
                overlap = overlap[1:]
            while overlap and sum(_message_tokens(item) for item in overlap) + message_tokens > max_chunk_tokens:
                overlap = overlap[1:]
            current = overlap
            current_tokens = sum(_message_tokens(item) for item in current)
            continue
        current.append(message)
        current_tokens += message_tokens
        index += 1
    if current:
        chunks.append(current)

    extraction_chunks: list[ExtractionChunk] = []
    for chunk_index, chunk_messages_ in enumerate(chunks, start=1):
        source_segment_ids = sorted(
            {int(item.source_segment_id) for item in chunk_messages_ if item.source_segment_id is not None}
        )
        extraction_chunks.append(
            ExtractionChunk(
                chunk_id=chunk_index,
                chunk_kind="conversation",
                token_start=chunk_messages_[0].message_index,
                token_end=chunk_messages_[-1].message_index,
                messages=chunk_messages_,
                text=_chunk_text(chunk_messages_),
                source_segment_ids=source_segment_ids,
                overlap_prev=chunk_index > 1,
                overlap_next=chunk_index < len(chunks),
            )
        )
    return extraction_chunks


def _message_tokens(message: MessageView) -> int:
    return estimate_token_count(f"{message.speaker_label} {message.occurred_at} {message.text}")


def _overlap_tail(messages: list[MessageView], overlap_tokens: int) -> list[MessageView]:
    if overlap_tokens <= 0:
        return []
    tail: list[MessageView] = []
    total = 0
    for message in reversed(messages):
        tail.insert(0, message)
        total += _message_tokens(message)
        if total >= overlap_tokens:
            break
    return tail


def _chunk_text(messages: list[MessageView]) -> str:
    lines = []
    for message in messages:
        prefix = f"[{message.occurred_at}] " if message.occurred_at else ""
        speaker = f"{message.speaker_label}: " if message.speaker_label else ""
        lines.append(f"{prefix}{speaker}{message.text}")
    return "\n".join(lines)

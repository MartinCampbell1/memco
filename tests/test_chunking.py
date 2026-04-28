from __future__ import annotations

from memco.extractors.chunking import chunk_messages
from memco.models.conversation import MessageView


def _message(index: int, text: str | None = None) -> MessageView:
    return MessageView(
        message_id=index,
        message_index=index,
        speaker_label="Alice" if index % 2 else "Bob",
        text=text or f"message {index} " + ("token " * 20),
        occurred_at=f"2024-01-{index:02d}T10:00:00Z",
        source_segment_id=index,
        session_id=1,
    )


def test_chunking_preserves_message_boundaries() -> None:
    chunks = chunk_messages([_message(1), _message(2), _message(3)], max_chunk_tokens=25, chunk_overlap_tokens=0)

    assert chunks
    assert all(message.text in chunk.text for chunk in chunks for message in chunk.messages)


def test_chunking_adds_overlap() -> None:
    messages = [_message(1, "alpha beta"), _message(2, "gamma delta"), _message(3, "epsilon zeta"), _message(4, "eta theta")]
    chunks = chunk_messages(messages, max_chunk_tokens=22, chunk_overlap_tokens=4)

    assert len(chunks) > 1
    assert chunks[0].overlap_next is True
    assert chunks[1].overlap_prev is True
    assert {item.message_id for item in chunks[0].messages} & {item.message_id for item in chunks[1].messages}


def test_chunking_keeps_session_datetime() -> None:
    chunks = chunk_messages([_message(1)], max_chunk_tokens=3000, chunk_overlap_tokens=300)

    assert chunks[0].messages[0].occurred_at == "2024-01-01T10:00:00Z"
    assert "2024-01-01T10:00:00Z" in chunks[0].text


def test_chunking_never_drops_turns() -> None:
    messages = [_message(index) for index in range(1, 8)]
    chunks = chunk_messages(messages, max_chunk_tokens=35, chunk_overlap_tokens=10)
    seen = {message.message_id for chunk in chunks for message in chunk.messages}

    assert {message.message_id for message in messages} <= seen

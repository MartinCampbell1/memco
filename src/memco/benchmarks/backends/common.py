from __future__ import annotations

from collections.abc import Callable

from memco.benchmarks.models import NormalizedConversation, NormalizedTurn
from memco.benchmarks.prompts import ANSWER_SYSTEM_PROMPT, ANSWER_USER_PROMPT
from memco.benchmarks.testing import fake_answer

AnswerFn = Callable[[str, str], str]


def estimate_tokens(text: str) -> int:
    return len(text.split())


def session_label(turn: NormalizedTurn) -> str:
    padded = f"session_{turn.session_index:02d}"
    date = turn.session_datetime or "unknown date"
    return f"[{padded} | {date}]"


def format_turns(turns: list[NormalizedTurn]) -> str:
    lines: list[str] = []
    current_session: str | None = None
    for turn in turns:
        label = session_label(turn)
        if label != current_session:
            if lines:
                lines.append("")
            lines.append(label)
            current_session = label
        lines.append(f"{turn.speaker_name}: {turn.text}")
    return "\n".join(lines).strip()


def grouped_session_texts(conversation: NormalizedConversation) -> list[tuple[str, str, list[NormalizedTurn]]]:
    sessions: dict[int, list[NormalizedTurn]] = {}
    for turn in conversation.turns:
        sessions.setdefault(turn.session_index, []).append(turn)
    results: list[tuple[str, str, list[NormalizedTurn]]] = []
    for session_index in sorted(sessions):
        turns = sessions[session_index]
        label = session_label(turns[0])
        results.append((f"session_{session_index:02d}", f"{label}\n" + format_turns(turns), turns))
    return results


def build_answer_prompt(*, question: str, target_speaker_name: str | None, context: str) -> str:
    return (
        ANSWER_SYSTEM_PROMPT
        + "\n\n"
        + ANSWER_USER_PROMPT.format(
            target_speaker_name=target_speaker_name or "unknown",
            question=question,
            context=context,
        )
    )


def deterministic_answer(*, question: str, context: str, answer_fn: AnswerFn | None = None) -> str:
    fn = answer_fn or (lambda q, c: fake_answer(question=q, context=c))
    return fn(question, context)

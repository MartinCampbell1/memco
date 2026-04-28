from __future__ import annotations

from memco.benchmarks.backends.base import BackendAnswerResult
from memco.benchmarks.judge import BinaryJudge, FixtureBinaryJudge, parse_judge_json
from memco.benchmarks.models import NormalizedQuestion


def _question(*, category: str | None = "single_hop", gold: str = "Lisbon") -> NormalizedQuestion:
    return NormalizedQuestion(
        question_id="q1",
        sample_id="s1",
        question="Where did Alice move?",
        gold_answer=gold,
        category=category,
    )


def _answer(text: str, *, refused: bool | None = False) -> BackendAnswerResult:
    return BackendAnswerResult(
        ok=True,
        backend_name="memco",
        sample_id="s1",
        question_id="q1",
        answer=text,
        elapsed_ms=1,
        refused=refused,
    )


def test_judge_parses_valid_json() -> None:
    result = parse_judge_json('{"score":1,"reason":"correct","error_type":"none"}')

    assert result.ok is True
    assert result.score == 1.0
    assert result.error_type == "none"


def test_judge_retries_invalid_json_once() -> None:
    calls: list[str] = []

    def generate(system_prompt: str, user_prompt: str) -> str:
        del system_prompt
        calls.append(user_prompt)
        if len(calls) == 1:
            return "not json"
        return '{"score":0,"reason":"fixed","error_type":"missing_fact"}'

    judge = BinaryJudge(model_name="fixture", generate=generate)
    result = judge.judge(question=_question(), answer=_answer("Berlin"))

    assert result.ok is True
    assert result.score == 0.0
    assert result.error_type == "missing_fact"
    assert result.raw["repaired"] is True
    assert len(calls) == 2


def test_judge_provider_exception_returns_judge_error() -> None:
    def generate(system_prompt: str, user_prompt: str) -> str:
        del system_prompt, user_prompt
        raise RuntimeError("provider unavailable")

    judge = BinaryJudge(model_name="live-model", generate=generate)
    result = judge.judge(question=_question(), answer=_answer("Lisbon"))

    assert result.ok is False
    assert result.label == "judge_error"
    assert result.error_type == "other"
    assert result.raw["provider_error"] == "provider unavailable"
    assert result.raw["prompt_backend_blind"] is True


def test_adversarial_refusal_scores_correct() -> None:
    question = _question(category="adversarial", gold="No evidence supports that.")
    result = FixtureBinaryJudge().judge(question=question, answer=_answer("I do not have supported evidence for that.", refused=True))

    assert result.score == 1.0
    assert result.error_type == "none"


def test_adversarial_false_premise_acceptance_scores_wrong() -> None:
    question = _question(category="adversarial", gold="No evidence supports that.")
    result = FixtureBinaryJudge().judge(question=question, answer=_answer("Yes, Alice has a sister."))

    assert result.score == 0.0
    assert result.error_type == "accepted_false_premise"


def test_judge_prompt_is_backend_blind() -> None:
    seen_prompts: list[str] = []

    def generate(system_prompt: str, user_prompt: str) -> str:
        del system_prompt
        seen_prompts.append(user_prompt)
        return '{"score":1,"reason":"correct","error_type":"none"}'

    judge = BinaryJudge(model_name="fixture", generate=generate)
    judge.judge(question=_question(), answer=_answer("Lisbon"))

    assert "memco" not in seen_prompts[0].casefold()

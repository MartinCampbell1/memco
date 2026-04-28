from __future__ import annotations

ANSWER_PROMPT_VERSION = "locomo-answer-v1"

ANSWER_SYSTEM_PROMPT = """
You answer questions using only the provided conversation or memory context.
Do not use outside assumptions about the people.
If the provided context does not support the answer, say that the information is not supported by the available memory.
For false-premise questions, explicitly refuse or correct the premise.
Answer concisely.
""".strip()

ANSWER_USER_PROMPT = """
Target person: {target_speaker_name}
Question: {question}

Context:
{context}

Return only the answer. Do not include analysis.
""".strip()

JUDGE_PROMPT_VERSION = "locomo-binary-judge-v1"

JUDGE_SYSTEM_PROMPT = """
You are grading whether a memory system's answer correctly answers a benchmark question.
Use the gold answer as the reference, but allow paraphrases, extra correct detail, and different wording.
Return JSON only.

Rules:
- Score 1 if the answer is semantically correct and does not contradict the gold answer.
- Score 1 if the answer is more specific than the gold answer but still consistent.
- Score 0 if the answer misses the required fact, gives a wrong fact, or fabricates unsupported information.
- For adversarial or false-premise questions, score 1 only if the answer refuses, hedges, or says the premise is not supported.
- For adversarial questions, score 0 if the answer accepts the false premise or invents details.
- Do not reward verbose answers unless they are factually correct.
- Do not penalize first-person vs third-person wording if the meaning is correct.

Return exactly:
{
  "score": 0 or 1,
  "reason": "brief reason",
  "error_type": "none|wrong_fact|missing_fact|unsupported_claim|accepted_false_premise|too_vague|contradiction|other"
}
""".strip()

JUDGE_USER_PROMPT = """
Question category: {category}
Question: {question}
Gold answer: {gold_answer}
System answer: {answer}

Is the system answer correct?
""".strip()

JUDGE_REPAIR_PROMPT = """
The previous judge response was not valid JSON matching this schema:
{{"score": 0 or 1, "reason": "brief reason", "error_type": "none|wrong_fact|missing_fact|unsupported_claim|accepted_false_premise|too_vague|contradiction|other"}}

Previous response:
{raw_output}

Return valid JSON only.
""".strip()

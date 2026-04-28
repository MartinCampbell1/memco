from __future__ import annotations

import hashlib
import math
import re


def fake_answer(*, question: str, context: str) -> str:
    lowered = question.casefold()
    candidates = {
        "lisbon": "Lisbon",
        "postgres": "Postgres",
        "python": "Python",
    }
    for needle, answer in candidates.items():
        if needle in context.casefold() and (needle in lowered or answer.casefold() in lowered):
            return answer
    if "where" in lowered and "moved to lisbon" in context.casefold():
        return "Lisbon"
    if "database" in lowered and "postgres" in context.casefold():
        return "Postgres"
    if "favorite tool" in lowered and "python" in context.casefold():
        return "Python"
    return "The information is not supported by the available memory."


def fake_summarize(*, previous_summary: str, session_text: str) -> str:
    facts: list[str] = []
    for line in session_text.splitlines():
        cleaned = line.strip()
        if not cleaned or cleaned.startswith("["):
            continue
        facts.append(cleaned)
    combined = "\n".join(item for item in [previous_summary, *facts] if item)
    return combined.strip()


def fake_embed(text: str) -> list[float]:
    tokens = re.findall(r"[a-z0-9]+", text.casefold())
    vector = [0.0] * 16
    for token in tokens:
        digest = hashlib.sha256(token.encode("utf-8")).digest()
        vector[digest[0] % len(vector)] += 1.0
    norm = math.sqrt(sum(value * value for value in vector)) or 1.0
    return [value / norm for value in vector]

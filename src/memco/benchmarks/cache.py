from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


PROMPT_VERSION = "locomo-runner-v1"


def benchmark_cache_key(
    *,
    dataset_sha256: str,
    backend_name: str,
    backend_version: str,
    sample_id: str,
    question_id: str,
    answer_model: str,
    judge_model: str,
    embedding_model: str,
    prompt_version: str = PROMPT_VERSION,
    code_git_commit: str,
) -> str:
    parts = [
        dataset_sha256,
        backend_name,
        backend_version,
        sample_id,
        question_id,
        answer_model,
        judge_model,
        embedding_model,
        prompt_version,
        code_git_commit,
    ]
    return hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()


class JsonBenchmarkCache:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self._entries: dict[str, dict[str, Any]] | None = None

    def _load(self) -> dict[str, dict[str, Any]]:
        if self._entries is None:
            if self.path.exists():
                self._entries = json.loads(self.path.read_text(encoding="utf-8"))
            else:
                self._entries = {}
        return self._entries

    def get(self, key: str, kind: str) -> dict[str, Any] | None:
        entry = self._load().get(key)
        if not entry or entry.get("kind") != kind:
            return None
        payload = entry.get("payload")
        return payload if isinstance(payload, dict) else None

    def set(self, key: str, *, kind: str, payload: dict[str, Any]) -> None:
        self._load()[key] = {"kind": kind, "payload": payload}

    def flush(self) -> None:
        entries = self._load()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(entries, indent=2, sort_keys=True) + "\n", encoding="utf-8")

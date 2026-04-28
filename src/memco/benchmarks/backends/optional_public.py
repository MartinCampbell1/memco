from __future__ import annotations

import importlib.util
import os
from typing import Any

from memco.benchmarks.backends.base import BackendAnswerResult, BackendIngestResult, MemoryBackend


class OptionalPublicAdapter(MemoryBackend):
    version = "optional-adapter-v1"
    package_name: str | None = None
    required_env: tuple[str, ...] = ()
    run_flag = "MEMCO_RUN_VENDOR_BENCHMARKS"

    def __init__(self) -> None:
        self.skipped_reason = self._skip_reason()

    def reset_sample(self, sample_id: str) -> None:
        del sample_id

    def ingest_conversation(self, conversation) -> BackendIngestResult:  # type: ignore[no-untyped-def]
        raise RuntimeError(self.skipped_reason or f"{self.name} adapter execution is not implemented in this checkout")

    def answer_question(self, question) -> BackendAnswerResult:  # type: ignore[no-untyped-def]
        raise RuntimeError(self.skipped_reason or f"{self.name} adapter execution is not implemented in this checkout")

    def report_config(self) -> dict[str, Any]:
        return {
            "backend_name": self.name,
            "status": "skipped" if self.skipped_reason else "available",
            "reason": self.skipped_reason,
            "package_name": self.package_name,
            "required_env": list(self.required_env),
        }

    def _skip_reason(self) -> str | None:
        if os.environ.get(self.run_flag, "").strip().lower() not in {"1", "true", "yes", "on"}:
            return f"{self.run_flag} is not enabled"
        if self.package_name and importlib.util.find_spec(self.package_name) is None:
            return f"{self.package_name} package is not installed"
        missing = [name for name in self.required_env if not os.environ.get(name)]
        if missing:
            return f"{', '.join(missing)} not set"
        return "optional public adapter execution is not wired for this private benchmark run"

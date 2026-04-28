from __future__ import annotations

from memco.benchmarks.backends.base import MemoryBackend
from memco.benchmarks.backends.langmem_backend import LangMemBenchmarkBackend
from memco.benchmarks.backends.mem0_backend import Mem0BenchmarkBackend
from memco.benchmarks.backends.zep_backend import ZepBenchmarkBackend


def test_mem0_adapter_skips_without_key(monkeypatch) -> None:
    monkeypatch.delenv("MEMCO_RUN_VENDOR_BENCHMARKS", raising=False)
    monkeypatch.delenv("MEM0_API_KEY", raising=False)

    backend = Mem0BenchmarkBackend()

    assert backend.skipped_reason
    assert backend.report_config()["status"] == "skipped"


def test_zep_adapter_skips_without_key(monkeypatch) -> None:
    monkeypatch.delenv("MEMCO_RUN_VENDOR_BENCHMARKS", raising=False)
    monkeypatch.delenv("ZEP_API_KEY", raising=False)

    backend = ZepBenchmarkBackend()

    assert backend.skipped_reason
    assert backend.report_config()["status"] == "skipped"


def test_langmem_adapter_skips_without_package(monkeypatch) -> None:
    monkeypatch.setenv("MEMCO_RUN_VENDOR_BENCHMARKS", "1")

    backend = LangMemBenchmarkBackend()

    assert backend.skipped_reason


def test_vendor_adapters_conform_to_backend_interface() -> None:
    for backend in (Mem0BenchmarkBackend(), ZepBenchmarkBackend(), LangMemBenchmarkBackend()):
        assert isinstance(backend, MemoryBackend)
        assert backend.name in {"mem0", "zep", "langmem"}

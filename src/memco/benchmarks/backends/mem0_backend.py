from __future__ import annotations

from memco.benchmarks.backends.optional_public import OptionalPublicAdapter


class Mem0BenchmarkBackend(OptionalPublicAdapter):
    name = "mem0"
    package_name = "mem0"
    required_env = ("MEM0_API_KEY",)

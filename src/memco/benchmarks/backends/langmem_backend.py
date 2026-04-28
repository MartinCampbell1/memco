from __future__ import annotations

from memco.benchmarks.backends.optional_public import OptionalPublicAdapter


class LangMemBenchmarkBackend(OptionalPublicAdapter):
    name = "langmem"
    package_name = "langmem"
    required_env: tuple[str, ...] = ()

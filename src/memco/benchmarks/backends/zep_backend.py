from __future__ import annotations

from memco.benchmarks.backends.optional_public import OptionalPublicAdapter


class ZepBenchmarkBackend(OptionalPublicAdapter):
    name = "zep"
    package_name = "zep_cloud"
    required_env = ("ZEP_API_KEY",)

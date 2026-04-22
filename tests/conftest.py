from __future__ import annotations

from pathlib import Path

import pytest

from memco.config import Settings
from memco.runtime import ensure_runtime


@pytest.fixture()
def project_root(tmp_path: Path) -> Path:
    return tmp_path / "memco-project"


@pytest.fixture()
def settings(project_root: Path) -> Settings:
    config = Settings(root=project_root)
    return ensure_runtime(config)

from __future__ import annotations

from memco.config import Settings, write_default_config
from memco.db import initialize_db


DIRS = [
    "var/db",
    "var/config",
    "var/raw",
]


def ensure_runtime(settings: Settings) -> Settings:
    settings.root.mkdir(parents=True, exist_ok=True)
    for relative in DIRS:
        (settings.root / relative).mkdir(parents=True, exist_ok=True)
    write_default_config(settings)
    initialize_db(settings.db_path)
    return settings

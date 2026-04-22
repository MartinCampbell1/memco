from __future__ import annotations

from fastapi import APIRouter

from memco.api.deps import get_settings
from memco.db import get_connection

router = APIRouter()


@router.get("/health")
def health():
    settings = get_settings()
    with get_connection(settings.db_path) as conn:
        workspace_row = conn.execute("SELECT COUNT(*) AS count FROM workspaces").fetchone()
        source_row = conn.execute("SELECT COUNT(*) AS count FROM sources").fetchone()
        person_row = conn.execute("SELECT COUNT(*) AS count FROM persons").fetchone()
        fact_row = conn.execute("SELECT COUNT(*) AS count FROM memory_facts").fetchone()
    return {
        "ok": True,
        "root": str(settings.root),
        "db": settings.database_target,
        "storage_engine": settings.storage.engine,
        "database_target": settings.database_target,
        "counts": {
            "workspaces": int(workspace_row["count"]),
            "sources": int(source_row["count"]),
            "persons": int(person_row["count"]),
            "facts": int(fact_row["count"]),
        },
    }

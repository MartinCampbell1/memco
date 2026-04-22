from __future__ import annotations

import os
from pathlib import Path

import psycopg
import pytest

from memco.postgres_smoke import run_postgres_smoke


def test_postgres_live_smoke_against_local_server(tmp_path):
    maintenance_url = os.environ.get("MEMCO_TEST_POSTGRES_URL", "postgresql://martin@127.0.0.1:5432/postgres")
    try:
        with psycopg.connect(maintenance_url):
            pass
    except Exception as exc:
        pytest.skip(f"local postgres maintenance database not reachable: {exc}")

    result = run_postgres_smoke(
        database_url=maintenance_url,
        root=Path(tmp_path / "runtime"),
        project_root=Path(__file__).resolve().parents[1],
    )

    assert result["health"]["storage_engine"] == "postgres"
    assert result["schema_migrations"] >= 1

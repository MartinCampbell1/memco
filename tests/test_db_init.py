from __future__ import annotations

from memco.db import get_connection


def test_runtime_initializes_schema(settings):
    with get_connection(settings.db_path) as conn:
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type IN ('table', 'view') ORDER BY name"
        ).fetchall()
    table_names = {str(row["name"]) for row in rows}
    assert "workspaces" in table_names
    assert "sources" in table_names
    assert "source_documents" in table_names
    assert "source_segments" in table_names
    assert "schema_migrations" in table_names
    assert "persons" in table_names
    assert "memory_facts" in table_names
    assert "review_queue" in table_names
    assert "memory_operations" in table_names

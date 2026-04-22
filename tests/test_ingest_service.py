from __future__ import annotations

from pathlib import Path

from memco.db import get_connection
from memco.services.ingest_service import IngestService


def test_simple_file_import_writes_raw_and_db(settings, tmp_path):
    source = tmp_path / "note.txt"
    source.write_text("Memco remembers explicit facts.\n\nEvidence first.", encoding="utf-8")

    service = IngestService()
    with get_connection(settings.db_path) as conn:
        result = service.import_file(
            settings,
            conn,
            workspace_slug="default",
            path=source,
            source_type="note",
        )

    assert Path(result.source_path).exists()
    assert Path(result.normalized_path).exists()
    with get_connection(settings.db_path) as conn:
        row = conn.execute("SELECT source_type, parsed_text FROM sources WHERE id = ?", (result.source_id,)).fetchone()
        assert row is not None
        assert row["source_type"] == "note"
        assert "Memco remembers" in row["parsed_text"]


def test_import_text_uses_title_and_writes_inside_runtime(settings):
    service = IngestService()
    with get_connection(settings.db_path) as conn:
        result = service.import_text(
            settings,
            conn,
            workspace_slug="default",
            text="Alice lives in Lisbon.",
            title="Alice Seed",
            source_type="note",
        )
        row = conn.execute(
            "SELECT title, source_path, origin_uri FROM sources WHERE id = ?",
            (result.source_id,),
        ).fetchone()

    assert row is not None
    assert result.title == "Alice Seed"
    assert row["title"] == "Alice Seed"
    assert "var/raw/note/" in row["source_path"]
    assert row["origin_uri"] == "inline://alice-seed"

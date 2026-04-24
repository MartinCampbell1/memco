from __future__ import annotations

import json
from pathlib import Path

import pytest

from memco.db import get_connection
from memco.services.ingest_service import IngestService, parse_document


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


def test_import_file_uses_token_window_source_chunks(settings, tmp_path):
    source = tmp_path / "long-note.txt"
    source.write_text(" ".join(f"word{i}" for i in range(620)), encoding="utf-8")

    service = IngestService()
    with get_connection(settings.db_path) as conn:
        result = service.import_file(
            settings,
            conn,
            workspace_slug="default",
            path=source,
            source_type="note",
        )
        rows = conn.execute(
            """
            SELECT token_count, locator_json
            FROM source_chunks
            WHERE source_id = ?
            ORDER BY chunk_index ASC
            """,
            (result.source_id,),
        ).fetchall()

    assert len(rows) == 2
    first_locator = json.loads(rows[0]["locator_json"])
    second_locator = json.loads(rows[1]["locator_json"])
    assert rows[0]["token_count"] == 500
    assert first_locator["token_window"]["max_tokens"] == 500
    assert first_locator["token_window"]["overlap_next"] is True
    assert second_locator["token_window"]["overlap_prev"] is True


def test_parse_document_rejects_explicit_unsupported_source_type(tmp_path):
    source = tmp_path / "note.txt"
    source.write_text("This suffix is supported, but the source_type is not.", encoding="utf-8")

    with pytest.raises(ValueError, match="unsupported source_type 'whatsapp'"):
        parse_document(source, source_type="whatsapp")


def test_import_file_rejects_source_type_outside_runtime_contract(settings, tmp_path):
    source = tmp_path / "note.txt"
    source.write_text("Unsupported imports should fail before persistence.", encoding="utf-8")

    service = IngestService()
    with get_connection(settings.db_path) as conn:
        with pytest.raises(ValueError, match="unsupported source_type 'whatsapp'"):
            service.import_file(
                settings,
                conn,
                workspace_slug="default",
                path=source,
                source_type="whatsapp",
            )

        count = conn.execute("SELECT COUNT(*) AS count FROM sources").fetchone()["count"]

    assert count == 0


def test_import_text_rejects_source_type_outside_runtime_contract(settings):
    service = IngestService()
    with get_connection(settings.db_path) as conn:
        with pytest.raises(ValueError, match="unsupported source_type 'whatsapp'"):
            service.import_text(
                settings,
                conn,
                workspace_slug="default",
                text="Alice lives in Lisbon.",
                title="Alice Seed",
                source_type="whatsapp",
            )


def test_import_file_normalizes_supported_source_type(settings, tmp_path):
    source = tmp_path / "note.txt"
    source.write_text("Source type casing should not create a new contract.", encoding="utf-8")

    service = IngestService()
    with get_connection(settings.db_path) as conn:
        result = service.import_file(
            settings,
            conn,
            workspace_slug="default",
            path=source,
            source_type=" NOTE ",
        )
        row = conn.execute("SELECT source_type FROM sources WHERE id = ?", (result.source_id,)).fetchone()

    assert result.source_type == "note"
    assert row["source_type"] == "note"


def test_markdown_import_extracts_frontmatter_metadata(settings, tmp_path):
    source = tmp_path / "profile.md"
    source.write_text(
        "\n".join(
            [
                "---",
                "title: Alice Profile",
                "date: 2026-04-24",
                "tags:",
                "  - memory",
                "---",
                "",
                "Alice lives in Lisbon.",
            ]
        ),
        encoding="utf-8",
    )

    service = IngestService()
    with get_connection(settings.db_path) as conn:
        result = service.import_file(
            settings,
            conn,
            workspace_slug="default",
            path=source,
            source_type="markdown",
        )
        row = conn.execute(
            "SELECT source_type, parsed_text, meta_json FROM sources WHERE id = ?",
            (result.source_id,),
        ).fetchone()

    assert row is not None
    meta = json.loads(row["meta_json"])
    assert row["source_type"] == "markdown"
    assert "Alice lives in Lisbon." in row["parsed_text"]
    assert "title: Alice Profile" not in row["parsed_text"]
    assert meta["parser_name"] == "markdown"
    assert meta["frontmatter"]["title"] == "Alice Profile"
    assert meta["frontmatter"]["date"] == "2026-04-24"
    assert meta["frontmatter"]["tags"] == ["memory"]


def test_html_import_extracts_visible_text_and_title(settings, tmp_path):
    source = tmp_path / "page.html"
    source.write_text(
        """
        <html>
          <head>
            <title>Alice Page</title>
            <style>.secret { display: none; }</style>
            <script>console.log("ignore me")</script>
          </head>
          <body>
            <main>
              <h1>Alice</h1>
              <p>Alice moved to Lisbon.</p>
            </main>
          </body>
        </html>
        """,
        encoding="utf-8",
    )

    service = IngestService()
    with get_connection(settings.db_path) as conn:
        result = service.import_file(
            settings,
            conn,
            workspace_slug="default",
            path=source,
            source_type="html",
        )
        row = conn.execute(
            "SELECT source_type, parsed_text, meta_json FROM sources WHERE id = ?",
            (result.source_id,),
        ).fetchone()

    assert row is not None
    meta = json.loads(row["meta_json"])
    assert row["source_type"] == "html"
    assert "# Alice Page" in row["parsed_text"]
    assert "Alice moved to Lisbon." in row["parsed_text"]
    assert "console.log" not in row["parsed_text"]
    assert meta["parser_name"] == "html"
    assert meta["title"] == "Alice Page"


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


def test_import_text_preserves_russian_utf8_content(settings):
    service = IngestService()
    with get_connection(settings.db_path) as conn:
        result = service.import_text(
            settings,
            conn,
            workspace_slug="default",
            text="Алиса живет в Lisbon и любит tea.",
            title="Русский Seed",
            source_type="note",
        )
        row = conn.execute(
            "SELECT title, parsed_text FROM sources WHERE id = ?",
            (result.source_id,),
        ).fetchone()

    assert row is not None
    assert row["title"] == "Русский Seed"
    assert "Алиса живет в Lisbon и любит tea." in row["parsed_text"]


def test_email_import_normalizes_headers_and_body(settings, tmp_path):
    source = tmp_path / "message.eml"
    source.write_text(
        "\n".join(
            [
                "From: Alice <alice@example.com>",
                "To: Bob <bob@example.com>",
                "Subject: Weekend plan",
                "Date: Tue, 21 Apr 2026 10:00:00 +0000",
                "Content-Type: text/plain; charset=utf-8",
                "",
                "Let's meet for coffee on Friday.",
            ]
        ),
        encoding="utf-8",
    )

    service = IngestService()
    with get_connection(settings.db_path) as conn:
        result = service.import_file(
            settings,
            conn,
            workspace_slug="default",
            path=source,
            source_type="email",
        )
        row = conn.execute("SELECT source_type, parsed_text, meta_json FROM sources WHERE id = ?", (result.source_id,)).fetchone()

    assert row is not None
    assert row["source_type"] == "email"
    assert "Subject: Weekend plan" in row["parsed_text"]
    assert "From: Alice <alice@example.com>" in row["parsed_text"]
    assert "Let's meet for coffee on Friday." in row["parsed_text"]
    assert Path(result.normalized_path).exists()


def test_email_parser_dispatch_uses_source_type_not_suffix(settings, tmp_path):
    source = tmp_path / "renamed-email.txt"
    source.write_text(
        "\n".join(
            [
                "From: Alice <alice@example.com>",
                "To: Bob <bob@example.com>",
                "Subject: Renamed export",
                "Date: Tue, 21 Apr 2026 10:00:00 +0000",
                "Content-Type: text/plain; charset=utf-8",
                "",
                "This is still an email even with a .txt suffix.",
            ]
        ),
        encoding="utf-8",
    )

    service = IngestService()
    with get_connection(settings.db_path) as conn:
        result = service.import_file(
            settings,
            conn,
            workspace_slug="default",
            path=source,
            source_type="email",
        )
        row = conn.execute("SELECT parsed_text, meta_json FROM sources WHERE id = ?", (result.source_id,)).fetchone()

    assert row is not None
    assert "Renamed export" in row["parsed_text"]
    assert "\"parser_name\": \"email\"" in row["meta_json"]
    assert "parser_confidence" in row["meta_json"]


def test_pdf_import_extracts_page_text(settings, tmp_path):
    try:
        from pypdf import PdfReader, PdfWriter
        from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject
    except ImportError:
        pytest.skip("pypdf optional dependency not available")

    source = tmp_path / "sample.pdf"
    writer = PdfWriter()
    page = writer.add_blank_page(width=300, height=144)
    content = DecodedStreamObject()
    content.set_data(b"BT /F1 12 Tf 36 100 Td (Hello PDF world) Tj ET")
    content_ref = writer._add_object(content)
    page[NameObject("/Contents")] = content_ref
    font_dict = writer._add_object(
        DictionaryObject(
            {
                NameObject("/Type"): NameObject("/Font"),
                NameObject("/Subtype"): NameObject("/Type1"),
                NameObject("/BaseFont"): NameObject("/Helvetica"),
            }
        )
    )
    page[NameObject("/Resources")] = writer._add_object(
        DictionaryObject(
            {
                NameObject("/Font"): DictionaryObject(
                    {
                        NameObject("/F1"): font_dict,
                    }
                )
            }
        )
    )
    with source.open("wb") as handle:
        writer.write(handle)

    # Quick sanity check that the generated fixture is readable by pypdf on this machine.
    reader = PdfReader(str(source))
    extracted = (reader.pages[0].extract_text() or "").strip()
    if "Hello PDF world" not in extracted:
        pytest.skip("local pypdf build could not extract generated PDF fixture text")

    service = IngestService()
    with get_connection(settings.db_path) as conn:
        result = service.import_file(
            settings,
            conn,
            workspace_slug="default",
            path=source,
            source_type="pdf",
        )
        row = conn.execute("SELECT source_type, parsed_text FROM sources WHERE id = ?", (result.source_id,)).fetchone()

    assert row is not None
    assert row["source_type"] == "pdf"
    assert "Hello PDF world" in row["parsed_text"]
    assert "## Page 1" in row["parsed_text"]


def test_pdf_import_records_page_quality_metadata(settings, tmp_path):
    try:
        from pypdf import PdfReader, PdfWriter
        from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject
    except ImportError:
        pytest.skip("pypdf optional dependency not available")

    def add_text_page(writer: PdfWriter, text_stream: bytes):
        page = writer.add_blank_page(width=300, height=144)
        content = DecodedStreamObject()
        content.set_data(text_stream)
        content_ref = writer._add_object(content)
        page[NameObject("/Contents")] = content_ref
        font_dict = writer._add_object(
            DictionaryObject(
                {
                    NameObject("/Type"): NameObject("/Font"),
                    NameObject("/Subtype"): NameObject("/Type1"),
                    NameObject("/BaseFont"): NameObject("/Helvetica"),
                }
            )
        )
        page[NameObject("/Resources")] = writer._add_object(
            DictionaryObject(
                {
                    NameObject("/Font"): DictionaryObject(
                        {
                            NameObject("/F1"): font_dict,
                        }
                    )
                }
            )
        )
        return page

    source = tmp_path / "quality.pdf"
    writer = PdfWriter()
    add_text_page(writer, b"BT /F1 12 Tf 14 TL 36 110 Td (First    PDF line) Tj T* (Second PDF line) Tj ET")
    writer.add_blank_page(width=300, height=144)
    add_text_page(writer, b"BT /F1 12 Tf 36 100 Td (Third page text) Tj ET")
    with source.open("wb") as handle:
        writer.write(handle)

    reader = PdfReader(str(source))
    extracted = "\n".join(page.extract_text() or "" for page in reader.pages)
    if "First" not in extracted or "Third page text" not in extracted:
        pytest.skip("local pypdf build could not extract generated PDF fixture text")

    service = IngestService()
    with get_connection(settings.db_path) as conn:
        result = service.import_file(
            settings,
            conn,
            workspace_slug="default",
            path=source,
            source_type="pdf",
        )
        row = conn.execute(
            "SELECT parsed_text, meta_json FROM sources WHERE id = ?",
            (result.source_id,),
        ).fetchone()

    assert row is not None
    meta = json.loads(row["meta_json"])
    assert "First PDF line" in row["parsed_text"]
    assert "Second PDF line" in row["parsed_text"]
    assert "Third page text" in row["parsed_text"]
    assert "## Page 2" not in row["parsed_text"]
    assert meta["parser_name"] == "pdf"
    assert meta["parser_confidence"] == 0.85
    assert meta["page_count"] == 3
    assert meta["extracted_page_count"] == 2
    assert meta["empty_page_numbers"] == [2]
    assert meta["pages"][1] == {"page_number": 2, "extracted_chars": 0, "empty": True}


def test_import_persists_parser_confidence(settings, tmp_path):
    source = tmp_path / "parser-confidence.txt"
    source.write_text("Parser confidence should be stored.", encoding="utf-8")

    service = IngestService()
    with get_connection(settings.db_path) as conn:
        result = service.import_file(
            settings,
            conn,
            workspace_slug="default",
            path=source,
            source_type="note",
        )
        row = conn.execute("SELECT meta_json FROM sources WHERE id = ?", (result.source_id,)).fetchone()

    assert row is not None
    assert "\"parser_confidence\": 1.0" in row["meta_json"]

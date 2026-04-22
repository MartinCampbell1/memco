from __future__ import annotations

import os
import re
import sqlite3
from pathlib import Path
from typing import Any

import yaml


SCHEMA_PATH = Path(__file__).with_name("schema.sql")
POSTGRES_SCHEMA_PATH = Path(__file__).with_name("migrations").joinpath("postgres", "0001_base.sql")
SQLITE_BASE_VERSION = "0001_sqlite_base"
POSTGRES_BASE_VERSION = "0001_postgres_base"


def _infer_storage(db_path: Path) -> tuple[str, str]:
    engine = os.environ.get("MEMCO_STORAGE_ENGINE", "").strip().lower()
    database_url = os.environ.get("MEMCO_DATABASE_URL", "")
    if engine and (engine != "postgres" or database_url):
        return engine, database_url

    resolved = db_path.expanduser().resolve()
    root = resolved.parent.parent.parent
    config_path = root / "var" / "config" / "settings.yaml"
    if config_path.exists():
        with config_path.open("r", encoding="utf-8") as handle:
            raw = yaml.safe_load(handle) or {}
        storage = raw.get("storage", {}) or {}
        engine = str(storage.get("engine", engine or "sqlite")).strip().lower()
        database_url = str(storage.get("database_url", database_url or "")).strip()
    return engine or "sqlite", database_url


def _sqlite_connection(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA foreign_keys=ON;")
    conn.execute("PRAGMA busy_timeout=5000;")
    return conn


class PostgresCursorWrapper:
    def __init__(self, cursor, *, lastrowid: int | None = None) -> None:
        self._cursor = cursor
        self.lastrowid = lastrowid

    def fetchone(self):
        return self._cursor.fetchone()

    def fetchall(self):
        return self._cursor.fetchall()


class PostgresConnectionWrapper:
    def __init__(self, conn) -> None:
        self._conn = conn
        self.engine = "postgres"

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if exc_type is None:
            self._conn.commit()
        else:
            self._conn.rollback()
        self._conn.close()

    def _translate_sql(self, sql: str) -> str:
        return sql.replace("?", "%s")

    def _insert_table_name(self, sql: str) -> str | None:
        match = re.match(r"\s*insert\s+into\s+([a-zA-Z_][a-zA-Z0-9_]*)", sql, re.IGNORECASE)
        if match is None:
            return None
        return match.group(1)

    def _lastrowid_for_insert(self, *, table_name: str) -> int | None:
        col_cursor = self._conn.cursor()
        col_cursor.execute(
            """
            SELECT 1
            FROM information_schema.columns
            WHERE table_name = %s AND column_name = 'id'
            LIMIT 1
            """,
            (table_name,),
        )
        if col_cursor.fetchone() is None:
            return None
        seq_cursor = self._conn.cursor()
        seq_cursor.execute("SELECT pg_get_serial_sequence(%s, 'id') AS seq", (table_name,))
        seq_row = seq_cursor.fetchone()
        if seq_row is None or not seq_row["seq"]:
            return None
        id_cursor = self._conn.cursor()
        id_cursor.execute("SELECT CURRVAL(%s) AS id", (seq_row["seq"],))
        row = id_cursor.fetchone()
        if row is None:
            return None
        return int(row["id"])

    def execute(self, sql: str, params: Any = None):
        translated = self._translate_sql(sql)
        cursor = self._conn.cursor()
        cursor.execute(translated, params or ())
        lastrowid = None
        if translated.lstrip().lower().startswith("insert into") and " returning " not in translated.lower():
            table_name = self._insert_table_name(translated)
            if table_name is not None:
                lastrowid = self._lastrowid_for_insert(table_name=table_name)
        return PostgresCursorWrapper(cursor, lastrowid=lastrowid)

    def executescript(self, script: str) -> None:
        for statement in _split_sql_statements(script):
            self.execute(statement)


def _postgres_connection(database_url: str):
    if not database_url:
        raise ValueError("MEMCO_DATABASE_URL or storage.database_url is required for postgres engine")
    try:
        import psycopg
        from psycopg.rows import dict_row
    except ImportError as exc:
        raise ImportError("psycopg is required for postgres storage.engine") from exc

    conn = psycopg.connect(database_url, row_factory=dict_row)
    return PostgresConnectionWrapper(conn)


def _split_sql_statements(script: str) -> list[str]:
    statements: list[str] = []
    buffer: list[str] = []
    in_quote = False
    previous = ""
    for char in script:
        if char == "'" and previous != "\\":
            in_quote = not in_quote
        if char == ";" and not in_quote:
            statement = "".join(buffer).strip()
            if statement:
                statements.append(statement)
            buffer = []
        else:
            buffer.append(char)
        previous = char
    tail = "".join(buffer).strip()
    if tail:
        statements.append(tail)
    return statements


def get_connection(db_path: Path) -> sqlite3.Connection:
    engine, database_url = _infer_storage(db_path)
    if engine == "postgres":
        return _postgres_connection(database_url)
    return _sqlite_connection(db_path)


def _is_postgres(conn) -> bool:
    return getattr(conn, "engine", "sqlite") == "postgres"


def _engine_sql(conn, *, sqlite_sql: str, postgres_sql: str) -> str:
    return postgres_sql if _is_postgres(conn) else sqlite_sql


def _table_columns(conn: sqlite3.Connection, table_name: str) -> set[str]:
    if _is_postgres(conn):
        rows = conn.execute(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_name = ?
            """,
            (table_name,),
        ).fetchall()
        return {str(row["column_name"]) for row in rows}
    rows = conn.execute(f"PRAGMA table_info({table_name})").fetchall()
    return {str(row["name"]) for row in rows}


def _ensure_column(conn: sqlite3.Connection, table_name: str, column_name: str, column_sql: str) -> None:
    if column_name in _table_columns(conn, table_name):
        return
    conn.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_sql}")


def _ensure_sessions_table(conn) -> None:
    conn.execute(
        _engine_sql(
            conn,
            sqlite_sql="""
            CREATE TABLE IF NOT EXISTS sessions (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              conversation_id INTEGER NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
              source_id INTEGER NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
              session_index INTEGER NOT NULL,
              session_uid TEXT NOT NULL,
              started_at TEXT NOT NULL DEFAULT '',
              ended_at TEXT NOT NULL DEFAULT '',
              detection_method TEXT NOT NULL DEFAULT 'single',
              meta_json TEXT NOT NULL DEFAULT '{}',
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL,
              UNIQUE(conversation_id, session_index),
              UNIQUE(conversation_id, session_uid)
            )
            """,
            postgres_sql="""
            CREATE TABLE IF NOT EXISTS sessions (
              id BIGSERIAL PRIMARY KEY,
              conversation_id BIGINT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
              source_id BIGINT NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
              session_index INTEGER NOT NULL,
              session_uid TEXT NOT NULL,
              started_at TEXT NOT NULL DEFAULT '',
              ended_at TEXT NOT NULL DEFAULT '',
              detection_method TEXT NOT NULL DEFAULT 'single',
              meta_json TEXT NOT NULL DEFAULT '{}',
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL,
              UNIQUE(conversation_id, session_index),
              UNIQUE(conversation_id, session_uid)
            )
            """,
        )
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_sessions_conversation_order ON sessions(conversation_id, session_index)"
    )


def _ensure_migrations_table(conn) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
          version TEXT PRIMARY KEY,
          applied_at TEXT NOT NULL
        )
        """
    )


def _migration_applied(conn, *, version: str) -> bool:
    row = conn.execute(
        "SELECT version FROM schema_migrations WHERE version = ?",
        (version,),
    ).fetchone()
    return row is not None


def _record_migration(conn, *, version: str) -> None:
    from memco.utils import isoformat_z

    conn.execute(
        "INSERT INTO schema_migrations (version, applied_at) VALUES (?, ?)",
        (version, isoformat_z()),
    )


def _apply_versioned_sql(conn, *, version: str, script: str) -> None:
    _ensure_migrations_table(conn)
    if _migration_applied(conn, version=version):
        return
    conn.executescript(script)
    _record_migration(conn, version=version)


def run_migrations(conn: sqlite3.Connection) -> None:
    session_fk_sql = _engine_sql(
        conn,
        sqlite_sql="INTEGER REFERENCES sessions(id) ON DELETE SET NULL",
        postgres_sql="BIGINT REFERENCES sessions(id) ON DELETE SET NULL",
    )
    _ensure_column(
        conn,
        "fact_candidates",
        "evidence_json",
        "evidence_json TEXT NOT NULL DEFAULT '[]'",
    )
    _ensure_column(
        conn,
        "memory_facts",
        "supersedes_fact_id",
        "supersedes_fact_id INTEGER REFERENCES memory_facts(id) ON DELETE SET NULL",
    )
    _ensure_column(
        conn,
        "memory_facts",
        "superseded_by_fact_id",
        "superseded_by_fact_id INTEGER REFERENCES memory_facts(id) ON DELETE SET NULL",
    )
    _ensure_column(
        conn,
        "memory_facts",
        "sensitivity",
        "sensitivity TEXT NOT NULL DEFAULT 'normal'",
    )
    _ensure_column(
        conn,
        "memory_facts",
        "visibility",
        "visibility TEXT NOT NULL DEFAULT 'standard'",
    )
    _ensure_column(
        conn,
        "memory_facts",
        "event_at",
        "event_at TEXT NOT NULL DEFAULT ''",
    )
    _ensure_column(
        conn,
        "memory_evidence",
        "source_segment_id",
        _engine_sql(
            conn,
            sqlite_sql="source_segment_id INTEGER REFERENCES source_segments(id) ON DELETE SET NULL",
            postgres_sql="source_segment_id BIGINT REFERENCES source_segments(id) ON DELETE SET NULL",
        ),
    )
    _ensure_sessions_table(conn)
    _ensure_column(
        conn,
        "conversation_messages",
        "session_id",
        f"session_id {session_fk_sql}",
    )
    _ensure_column(
        conn,
        "conversation_chunks",
        "session_id",
        f"session_id {session_fk_sql}",
    )
    _ensure_column(
        conn,
        "source_segments",
        "session_id",
        f"session_id {session_fk_sql}",
    )
    _ensure_column(
        conn,
        "fact_candidates",
        "session_id",
        f"session_id {session_fk_sql}",
    )
    _ensure_column(
        conn,
        "memory_evidence",
        "session_id",
        f"session_id {session_fk_sql}",
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_conversation_messages_session ON conversation_messages(session_id, message_index)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_conversation_chunks_session ON conversation_chunks(session_id, chunk_index)"
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_source_segments_session ON source_segments(session_id)")


def initialize_db(db_path: Path) -> None:
    with get_connection(db_path) as conn:
        engine, _ = _infer_storage(db_path)
        if engine == "postgres":
            _apply_versioned_sql(
                conn,
                version=POSTGRES_BASE_VERSION,
                script=POSTGRES_SCHEMA_PATH.read_text(encoding="utf-8"),
            )
        else:
            _apply_versioned_sql(
                conn,
                version=SQLITE_BASE_VERSION,
                script=SCHEMA_PATH.read_text(encoding="utf-8"),
            )
        run_migrations(conn)

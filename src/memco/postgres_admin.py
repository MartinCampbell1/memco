from __future__ import annotations

from urllib.parse import urlsplit, urlunsplit

import psycopg


def build_database_url(*, database_url: str, db_name: str) -> str:
    parts = urlsplit(database_url)
    return urlunsplit((parts.scheme, parts.netloc, f"/{db_name}", parts.query, parts.fragment))


def ensure_postgres_database(*, maintenance_database_url: str, db_name: str) -> str:
    target_url = build_database_url(database_url=maintenance_database_url, db_name=db_name)
    with psycopg.connect(maintenance_database_url, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (db_name,))
            if cur.fetchone() is None:
                cur.execute(f'CREATE DATABASE "{db_name}"')
    return target_url


def drop_postgres_database(*, maintenance_database_url: str, db_name: str) -> None:
    with psycopg.connect(maintenance_database_url, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = %s",
                (db_name,),
            )
            cur.execute(f'DROP DATABASE IF EXISTS "{db_name}"')

from __future__ import annotations

import os
import random
import socket
import subprocess
import time
import urllib.request
from pathlib import Path

import psycopg
from memco.postgres_admin import drop_postgres_database, ensure_postgres_database


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _wait_http(url: str, *, timeout_seconds: int = 20) -> dict:
    started = time.time()
    while time.time() - started < timeout_seconds:
        try:
            with urllib.request.urlopen(url, timeout=2) as response:
                import json

                return json.loads(response.read().decode("utf-8"))
        except Exception:
            time.sleep(0.5)
    raise TimeoutError(f"Timed out waiting for {url}")


def run_postgres_smoke(
    *,
    database_url: str,
    root: Path,
    port: int | None = None,
    project_root: Path,
) -> dict:
    selected_port = int(port or _free_port())
    db_name = f"memco_smoke_{random.randint(10000, 99999)}"

    run_db_url = ensure_postgres_database(
        maintenance_database_url=database_url,
        db_name=db_name,
    )
    env = {
        **os.environ,
        "MEMCO_STORAGE_ENGINE": "postgres",
        "MEMCO_DATABASE_URL": run_db_url,
        "MEMCO_ROOT": str(root),
        "MEMCO_API_PORT": str(selected_port),
        "MEMCO_API_HOST": "127.0.0.1",
    }

    process = subprocess.Popen(
        ["uv", "run", "memco-api"],
        cwd=str(project_root),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    try:
        payload = _wait_http(f"http://127.0.0.1:{selected_port}/health")
        if payload.get("storage_engine") != "postgres":
            raise RuntimeError("health did not report postgres storage engine")
        with psycopg.connect(run_db_url) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) FROM schema_migrations")
                count = int(cur.fetchone()[0])
                if count < 1:
                    raise RuntimeError("schema_migrations was empty")
        return {
            "health": payload,
            "schema_migrations": count,
            "database_url": run_db_url,
            "root": str(root),
            "port": selected_port,
        }
    finally:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
        drop_postgres_database(
            maintenance_database_url=database_url,
            db_name=db_name,
        )

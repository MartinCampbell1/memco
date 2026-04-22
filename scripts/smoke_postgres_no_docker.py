from __future__ import annotations

import os
import sys
from pathlib import Path

from memco.postgres_smoke import run_postgres_smoke


def main() -> int:
    database_url = os.environ.get("MEMCO_DATABASE_URL")
    if not database_url:
        print("MEMCO_DATABASE_URL is required", file=sys.stderr)
        return 2

    root = Path(os.environ.get("MEMCO_ROOT", "/tmp/memco-postgres-smoke")).resolve()
    port = int(os.environ["MEMCO_API_PORT"]) if os.environ.get("MEMCO_API_PORT") else None
    result = run_postgres_smoke(
        database_url=database_url,
        root=root,
        port=port,
        project_root=Path(__file__).resolve().parents[1],
    )
    print(result["health"])
    print({"schema_migrations": result["schema_migrations"]})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

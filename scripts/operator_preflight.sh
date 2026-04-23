#!/usr/bin/env sh
set -eu

PROJECT_ROOT="${MEMCO_ROOT:-$(pwd)}"
POSTGRES_DATABASE_URL="${MEMCO_POSTGRES_DATABASE_URL:-${1:-}}"

if [ -z "$POSTGRES_DATABASE_URL" ]; then
  echo "usage: MEMCO_POSTGRES_DATABASE_URL=postgresql://USER@HOST:PORT/postgres scripts/operator_preflight.sh" >&2
  echo "or: scripts/operator_preflight.sh postgresql://USER@HOST:PORT/postgres" >&2
  exit 2
fi

PYTHONPATH="$PROJECT_ROOT/src" "$PROJECT_ROOT/.venv/bin/memco" operator-preflight \
  --project-root "$PROJECT_ROOT" \
  --postgres-database-url "$POSTGRES_DATABASE_URL" \
  --output "$PROJECT_ROOT/var/reports/operator-preflight-current.json"

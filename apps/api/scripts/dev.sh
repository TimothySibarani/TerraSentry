#!/usr/bin/env bash
# Dev preflight: migrate SQLite, then run FastAPI with a scoped reloader.
# Run from the repo root (apps/api's `pnpm dev` does this).
set -euo pipefail

if [ -f .env ]; then
  set -a
  # shellcheck disable=SC1091
  . ./.env
  set +a
fi

echo "[dev] applying migrations..."
uv run alembic -c apps/api/alembic.ini upgrade head

exec uv run fastapi dev apps/api/src/terrasentry_api/main.py \
  --reload-dir apps/api/src --reload-dir python

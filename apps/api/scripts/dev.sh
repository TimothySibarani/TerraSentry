#!/usr/bin/env bash
# Dev preflight: start local Postgres + Redis, migrate, then run FastAPI with a scoped reloader.
# Run from the repo root (apps/api's `pnpm dev` does this).
set -euo pipefail

if [ -f .env ]; then
  set -a
  # shellcheck disable=SC1091
  . ./.env
  set +a
fi

db_url="${DATABASE_URL:-postgresql+asyncpg://postgres:postgres@localhost:5432/terrasentry}"
redis_url="${REDIS_URL:-redis://localhost:6379/0}"
local_infra=1
case "$db_url" in *@localhost:* | *@127.0.0.1:*) ;; *) local_infra=0 ;; esac
case "${CACHE_BACKEND:-redis}" in redis) case "$redis_url" in *//localhost:* | *//127.0.0.1:*) ;; *) local_infra=0 ;; esac ;; esac

if [ "$local_infra" = 1 ] && case "$db_url" in postgresql*) true ;; *) false ;; esac; then
  if command -v docker >/dev/null 2>&1; then
    echo "[dev] ensuring Postgres + Redis are running (docker compose up -d --wait)..."
    docker compose up -d --wait postgres redis
  else
    echo "[dev] docker not found; assuming Postgres/Redis are already running." >&2
  fi
else
  echo "[dev] DATABASE_URL/REDIS_URL are not local; skipping docker infrastructure."
fi

echo "[dev] applying migrations..."
uv run alembic -c apps/api/alembic.ini upgrade head

exec uv run fastapi dev apps/api/src/terrasentry_api/main.py \
  --reload-dir apps/api/src --reload-dir python

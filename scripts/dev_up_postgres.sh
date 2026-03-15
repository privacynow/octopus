#!/usr/bin/env bash
# Optional: start Postgres, run DB bootstrap/update and doctor. Use when you set BOT_DATABASE_URL.
# For default Local Runtime (SQLite) you do not need this script.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_DIR"

echo "Starting Postgres..."
docker compose up -d postgres

echo "Waiting for Postgres to be ready..."
for i in $(seq 1 30); do
  if docker compose exec postgres pg_isready -U bot -d bot 2>/dev/null; then
    break
  fi
  if [ "$i" -eq 30 ]; then
    echo "Postgres did not become ready in time." >&2
    exit 1
  fi
  sleep 1
done

echo "Running DB update (existing schema)..."
set +e
update_out=$(docker compose --profile tools run --rm db-update 2>&1)
update_rc=$?
set -e
if [ "$update_rc" -eq 0 ]; then
  echo "$update_out"
  echo "Running DB doctor..."
  docker compose --profile tools run --rm db-doctor
elif echo "$update_out" | grep -q "Schema or schema_migrations table missing"; then
  echo "Schema missing; running DB bootstrap (fresh schema)..."
  docker compose --profile tools run --rm db-bootstrap
  echo "Running DB doctor..."
  docker compose --profile tools run --rm db-doctor
else
  echo "DB update failed." >&2
  echo "$update_out" >&2
  exit 1
fi

echo "Postgres stack ready. Set BOT_DATABASE_URL=postgresql://bot:bot@postgres:5432/bot in .env.bot to use it."

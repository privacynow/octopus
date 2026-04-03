#!/usr/bin/env bash
# Start Postgres, run DB bootstrap/update and doctor for the standard runtime.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$REPO_DIR"

echo "Starting Postgres..."
docker compose --project-directory . -f infra/compose/docker-compose.yml up -d postgres

echo "Waiting for Postgres to be ready..."
for i in $(seq 1 30); do
  if docker compose --project-directory . -f infra/compose/docker-compose.yml exec postgres pg_isready -U bot -d bot 2>/dev/null; then
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
update_out=$(docker compose --project-directory . -f infra/compose/docker-compose.yml --profile tools run --rm db-update 2>&1)
update_rc=$?
set -e
if [ "$update_rc" -eq 0 ]; then
  echo "$update_out"
  echo "Running DB doctor..."
  docker compose --project-directory . -f infra/compose/docker-compose.yml --profile tools run --rm db-doctor
elif echo "$update_out" | grep -q "Schema or schema_migrations table missing"; then
  echo "Schema missing; running DB bootstrap (fresh schema)..."
  docker compose --project-directory . -f infra/compose/docker-compose.yml --profile tools run --rm db-bootstrap
  echo "Running DB doctor..."
  docker compose --project-directory . -f infra/compose/docker-compose.yml --profile tools run --rm db-doctor
else
  echo "This does not look like a fresh database. The error was:" >&2
  echo "$update_out" >&2
  echo "rerun ./scripts/db/dev_up_postgres.sh after fixing the issue." >&2
  exit 1
fi

echo "Postgres stack ready. Set OCTOPUS_DATABASE_URL=postgresql://bot:bot@postgres:5432/bot in the bot env file."
echo "To run the bot: ./octopus"

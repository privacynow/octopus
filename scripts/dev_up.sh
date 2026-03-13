#!/usr/bin/env bash
# Convenience: start Postgres, run DB bootstrap and doctor. See README.md.
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

echo "Running DB bootstrap..."
docker compose --profile tools run --rm db-bootstrap

echo "Running DB doctor..."
docker compose --profile tools run --rm db-doctor

echo "Tooling stack ready (Postgres + bootstrap + doctor). No bot runtime config was required."
echo "To run the bot:"
echo "  - Container (primary path): create an env file (e.g. .env.bot) with TELEGRAM_BOT_TOKEN, BOT_PROVIDER, BOT_ALLOWED_USERS (BOT_DATABASE_URL for container is set by Compose to postgres:5432). Run: docker compose run --rm --env-file .env.bot bot"
echo "  - Use a runnable image that includes the chosen provider CLI; see README.md."
echo "  - Host-run remains available as an advanced fallback/debug path; see docs/ARCHITECTURE.md."

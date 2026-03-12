#!/usr/bin/env bash
# Convenience: start Postgres, run DB bootstrap and doctor. See docs/PHASE12-OPERATIONAL-CONTRACT.md.
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

echo "Done. Set BOT_DATABASE_URL=postgresql://bot:bot@localhost:5432/bot in your .env, then: docker compose up bot"

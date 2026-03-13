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
echo "  1. Create .env.bot (TELEGRAM_BOT_TOKEN, BOT_PROVIDER, BOT_ALLOWED_USERS or BOT_ALLOW_OPEN=1)"
echo "  2. Build the bot image: ./scripts/build_bot_image.sh"
echo "  3. Provider login (one-time): ./scripts/provider_login.sh"
echo "  4. Start the bot: docker compose --profile bot --env-file .env.bot up -d bot   (or ./scripts/guided_start.sh for a single guided flow)"
echo "  See README.md. Host-run is an advanced fallback; see docs/ARCHITECTURE.md."

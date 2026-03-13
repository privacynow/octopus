#!/usr/bin/env bash
# Report provider auth and runtime health only (not DB or Telegram).
# Uses same image and bot-home volume as the bot. Requires .env.bot.
# For full app health use: docker compose run --rm --env-file .env.bot bot python -m app.main --doctor
set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_DIR"

if [ ! -f .env.bot ]; then
  echo "Create .env.bot first." >&2
  exit 1
fi

echo "Provider auth and runtime only (no DB/Telegram checks):"
docker compose --profile bot run --rm --env-file .env.bot bot-provider

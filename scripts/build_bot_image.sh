#!/usr/bin/env bash
# Build the supported bot image for the chosen provider (real Claude or Codex CLI).
# Reads BOT_PROVIDER from .env.bot if present, or use first argument: claude | codex.
# Usage: ./scripts/build_bot_image.sh [claude|codex]
set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_DIR"

provider=""
if [ -n "${1:-}" ]; then
  provider="$1"
elif [ -f .env.bot ]; then
  provider=$(grep -E '^\s*BOT_PROVIDER=' .env.bot 2>/dev/null | sed 's/.*=\s*//' | tr -d '\r' | tr -d '"' | tr -d "'" || true)
fi
if [ -z "$provider" ]; then
  provider="claude"
fi
case "$provider" in
  claude|codex) ;;
  *)
    echo "BOT_PROVIDER must be 'claude' or 'codex', got: $provider" >&2
    echo "Usage: $0 [claude|codex]" >&2
    echo "  Or set BOT_PROVIDER in .env.bot and run $0" >&2
    exit 1
    ;;
esac

echo "Building bot image for provider: $provider"
docker build -f Dockerfile.bot --build-arg BOT_PROVIDER="$provider" -t "telegram-agent-bot:$provider" "$REPO_DIR"
echo "Done. Start the bot with: docker compose --profile bot --env-file .env.bot up -d bot  (or ./scripts/guided_start.sh)"

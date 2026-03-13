#!/usr/bin/env bash
# Guided provider CLI login: interactive auth, then verify with --provider-health only.
# Reads BOT_PROVIDER from .env.bot; uses same image and bot-home volume as the bot.
# Run after: ./scripts/build_bot_image.sh and with .env.bot created.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_DIR"

if [ ! -f .env.bot ]; then
  echo "Create .env.bot first (TELEGRAM_BOT_TOKEN, BOT_PROVIDER, BOT_ALLOWED_USERS or BOT_ALLOW_OPEN=1)." >&2
  exit 1
fi

provider=""
if [ -n "${1:-}" ]; then
  provider="$1"
else
  provider=$(grep -E '^\s*BOT_PROVIDER=' .env.bot 2>/dev/null | sed 's/.*=\s*//' | tr -d '\r' | tr -d '"' | tr -d "'" || true)
fi
if [ -z "$provider" ]; then
  provider="claude"
fi
case "$provider" in
  claude|codex) ;;
  *)
    echo "BOT_PROVIDER must be 'claude' or 'codex', got: $provider" >&2
    exit 1
    ;;
esac

# Ensure the provider image exists; otherwise we may run the wrong image and get "codex: not found" etc.
if ! docker image inspect "telegram-agent-bot:$provider" >/dev/null 2>&1; then
  echo "Image telegram-agent-bot:$provider not found." >&2
  echo "Run: ./scripts/build_bot_image.sh $provider" >&2
  echo "Then run this script again." >&2
  exit 1
fi

# Image selection uses BOT_PROVIDER at Compose parse time (--env-file and shell). Pass it so we run the correct image.
echo "Provider login (BOT_PROVIDER=$provider). Uses same image and bot-home volume as the bot (no Postgres required)."
BOT_PROVIDER="$provider" docker compose --profile bot run --rm --env-file .env.bot -e "BOT_PROVIDER=$provider" bot-provider sh /app/scripts/container_provider_login.sh

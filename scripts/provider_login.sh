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

# Ensure the bot image was built for this provider; otherwise we may run the wrong image and get "codex: not found" etc.
if [ -f .bot-provider-built ]; then
  built_provider=$(cat .bot-provider-built 2>/dev/null || true)
  if [ -n "$built_provider" ] && [ "$built_provider" != "$provider" ]; then
    echo "Bot image was built for '$built_provider' but login is for '$provider'." >&2
    echo "Run: ./scripts/build_bot_image.sh $provider" >&2
    echo "Then run this script again." >&2
    exit 1
  fi
else
  echo "No bot image build recorded. Build the image for your provider first:" >&2
  echo "  ./scripts/build_bot_image.sh $provider" >&2
  echo "Then run this script again." >&2
  exit 1
fi

echo "Provider login (BOT_PROVIDER=$provider). Uses same image and bot-home volume as the bot."
echo "Postgres must be up (e.g. ./scripts/dev_up.sh)."
docker compose run --rm --env-file .env.bot -e "BOT_PROVIDER=$provider" bot sh /app/scripts/container_provider_login.sh

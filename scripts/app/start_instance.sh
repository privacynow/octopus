#!/usr/bin/env bash
# Start one Docker bot instance from its env file.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$REPO_DIR"
# shellcheck source=scripts/lib/bot.sh
. "$REPO_DIR/scripts/lib/bot.sh"
# shellcheck source=scripts/lib/docker.sh
. "$REPO_DIR/scripts/lib/docker.sh"

INSTANCE="${1:-default}"
if [ "$INSTANCE" = "default" ]; then
  BOT_ENV_FILE=".env.bot"
else
  BOT_ENV_FILE=".env.bot.$INSTANCE"
fi
export BOT_ENV_FILE

check_env_bot_required "$BOT_ENV_FILE"
telegram_token="$(grep -E '^\s*TELEGRAM_BOT_TOKEN=' "$BOT_ENV_FILE" 2>/dev/null | sed 's/.*=\s*//' | tr -d '\r' | tr -d '"' | tr -d "'" || true)"
require_real_telegram_token "$telegram_token" "$BOT_ENV_FILE"
bot_compose up -d bot

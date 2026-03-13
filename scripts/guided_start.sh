#!/usr/bin/env bash
# Single guided path: Postgres, .env.bot, build, provider login, then start the bot.
# For non-technical users who want one flow instead of several manual steps.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_DIR"

echo "=== Guided setup and start ==="

# 1. .env.bot
if [ ! -f .env.bot ]; then
  echo "Create .env.bot first with: TELEGRAM_BOT_TOKEN, BOT_PROVIDER (claude or codex), and BOT_ALLOWED_USERS or BOT_ALLOW_OPEN=1"
  echo "Example:"
  echo "  TELEGRAM_BOT_TOKEN=<from @BotFather>"
  echo "  BOT_PROVIDER=claude"
  echo "  BOT_ALLOWED_USERS=123456789"
  echo "See README.md Quick Start step 3."
  exit 1
fi

env_provider=$(grep -E '^\s*BOT_PROVIDER=' .env.bot 2>/dev/null | sed 's/.*=\s*//' | tr -d '\r' | tr -d '"' | tr -d "'" || true)
env_provider="${env_provider:-claude}"

# 2. Provider drift: did they change BOT_PROVIDER since last build?
if [ -f .bot-provider-built ]; then
  built_provider=$(cat .bot-provider-built 2>/dev/null || true)
  if [ -n "$built_provider" ] && [ "$built_provider" != "$env_provider" ]; then
    echo "BOT_PROVIDER in .env.bot ($env_provider) differs from last build ($built_provider)."
    echo "Rebuilding image for $env_provider; you will need to run provider login after."
    echo ""
  fi
fi

# 3. Postgres + bootstrap + doctor
echo "Step 1/4: Postgres and database..."
./scripts/dev_up.sh

# 4. Build bot image
echo ""
echo "Step 2/4: Building bot image for $env_provider..."
./scripts/build_bot_image.sh "$env_provider"

# 5. Provider login (prompt to run if not already OK)
echo ""
echo "Step 3/4: Provider auth..."
if ./scripts/provider_status.sh >/dev/null 2>&1; then
  echo "Provider already authenticated."
else
  echo "Run provider login (one-time, interactive):"
  echo "  ./scripts/provider_login.sh"
  echo "Then run this script again to start the bot, or run: docker compose up -d bot"
  exit 0
fi

# 6. Start bot
echo ""
echo "Step 4/4: Starting bot (background service)..."
docker compose up -d bot

echo ""
echo "Bot started. Message it in Telegram to use it."
echo "Logs: docker compose logs -f bot   Stop: docker compose stop bot"

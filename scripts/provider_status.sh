#!/usr/bin/env bash
# Report provider auth and runtime health only (not DB or Telegram).
# Uses same image and bot-home volume as the bot. Requires .env.bot.
# For full app health use: docker compose --profile bot run --rm --env-file .env.bot bot python -m app.main --doctor
set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_DIR"
# shellcheck source=scripts/lib_env.sh
. "$(dirname "$0")/lib_env.sh"

check_env_bot_required
provider=$(get_bot_provider)
check_provider_image "$provider" >/dev/null

echo "Provider auth and runtime only (no DB/Telegram checks):"
if ! docker compose --profile bot run --rm --env-file .env.bot bot-provider; then
  exit 1
fi
echo "For full app health (DB, config, Telegram) run: docker compose --profile bot run --rm --env-file .env.bot bot python -m app.main --doctor"

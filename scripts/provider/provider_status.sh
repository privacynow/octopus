#!/usr/bin/env bash
# Report provider auth and runtime health only (not DB or Telegram).
# Uses same image and bot-home volume as the bot. Requires .env.bot.
# For full app health use: docker compose --project-directory . -f infra/compose/docker-compose.yml --profile bot --env-file .env.bot run --rm bot python -m app.main --doctor
set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$REPO_DIR"
# shellcheck source=scripts/lib_env.sh
. "$REPO_DIR/scripts/lib_env.sh"

env_file="$(current_bot_env_file "${1:-}")"
BOT_ENV_FILE="$env_file"
export BOT_ENV_FILE
check_env_bot_required "$env_file"
provider=$(get_bot_provider "$env_file")
check_provider_image "$provider" >/dev/null

echo "Provider auth and runtime only (no DB/Telegram checks)."
if ! bot_compose run --rm bot-provider; then
  exit 1
fi
echo "Success here does NOT prove the bot can start. For full app health (DB, config, Telegram) run: docker compose --project-directory . -f infra/compose/docker-compose.yml --profile bot --env-file $env_file run --rm bot python -m app.main --doctor"

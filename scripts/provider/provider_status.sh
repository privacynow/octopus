#!/usr/bin/env bash
# Report provider auth and runtime health only (not DB or Telegram).
# Uses shared per-provider auth under .deploy/provider-auth/<provider>.
# For full app health use: docker compose --project-directory . -f infra/compose/docker-compose.yml --profile bot --env-file .env.bot run --rm bot python -m app.main --doctor
set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$REPO_DIR"
# shellcheck source=scripts/lib/bot.sh
. "$REPO_DIR/scripts/lib/bot.sh"
# shellcheck source=scripts/lib/docker.sh
. "$REPO_DIR/scripts/lib/docker.sh"
# shellcheck source=scripts/lib/provider.sh
. "$REPO_DIR/scripts/lib/provider.sh"

if [ -n "${1:-}" ]; then
  case "$1" in
    claude|codex) provider="$1" ;;
    *)
      echo "BOT_PROVIDER must be 'claude' or 'codex', got: $1" >&2
      exit 1
      ;;
  esac
  env_file=".env.bot"
else
  env_file="$(current_bot_env_file)"
  BOT_ENV_FILE="$env_file"
  export BOT_ENV_FILE
  check_env_bot_required "$env_file"
  provider=$(get_bot_provider "$env_file")
fi
check_provider_image "$provider" >/dev/null
ensure_provider_auth_dir "$provider"

echo "Provider auth and runtime only (no DB/Telegram checks)."
if ! provider_compose "$provider" run --rm bot-provider; then
  update_provider_auth_hint "$provider" "false"
  exit 1
fi
update_provider_auth_hint "$provider" "true"
echo "Success here does NOT prove the bot can start. For full app health (DB, config, Telegram) run: docker compose --project-directory . -f infra/compose/docker-compose.yml --profile bot --env-file $env_file run --rm bot python -m app.main --doctor"

#!/usr/bin/env bash
# Guided provider CLI login: interactive auth, then verify with --provider-health only.
# Reads BOT_PROVIDER from .env.bot; uses same image and bot-home volume as the bot.
# Run after: ./scripts/build_bot_image.sh and with .env.bot created.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_DIR"
# shellcheck source=scripts/lib_env.sh
. "$(dirname "$0")/lib_env.sh"

check_env_bot_required
if [ -n "${1:-}" ]; then
  case "$1" in
    claude|codex) provider="$1" ;;
    *)
      echo "BOT_PROVIDER must be 'claude' or 'codex', got: $1" >&2
      exit 1
      ;;
  esac
  check_provider_image "$provider" >/dev/null
else
  provider=$(get_bot_provider)
  check_provider_image "$provider" >/dev/null
fi

# Image selection uses BOT_PROVIDER at Compose parse time (--env-file and shell). Pass it so we run the correct image.
echo "Provider login (BOT_PROVIDER=$provider). Uses same image and bot-home volume as the bot (no Postgres required)."
BOT_PROVIDER="$provider" docker compose --profile bot run --rm --env-file .env.bot -e "BOT_PROVIDER=$provider" bot-provider sh /app/scripts/container_provider_login.sh

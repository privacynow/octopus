#!/usr/bin/env bash
# Stop one Docker bot instance.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$REPO_DIR"
# shellcheck source=scripts/lib/bot.sh
. "$REPO_DIR/scripts/lib/bot.sh"
# shellcheck source=scripts/lib/state.sh
. "$REPO_DIR/scripts/lib/state.sh"
# shellcheck source=scripts/lib/docker.sh
. "$REPO_DIR/scripts/lib/docker.sh"

SLUG="${1:-}"
[ -n "$SLUG" ] || {
  echo "Usage: ./scripts/app/stop_instance.sh <slug>" >&2
  echo "Run ./octopus status to list bots." >&2
  exit 1
}
BOT_ENV_FILE="$(bot_env_file "$SLUG")"
export BOT_ENV_FILE
check_env_bot_required "$BOT_ENV_FILE"
bot_compose "$SLUG" stop bot

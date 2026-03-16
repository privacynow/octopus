#!/usr/bin/env bash
# Start one Docker bot instance from its env file.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$REPO_DIR"
# shellcheck source=scripts/lib_env.sh
. "$REPO_DIR/scripts/lib_env.sh"

INSTANCE="${1:-default}"
if [ "$INSTANCE" = "default" ]; then
  BOT_ENV_FILE=".env.bot"
else
  BOT_ENV_FILE=".env.bot.$INSTANCE"
fi
export BOT_ENV_FILE

check_env_bot_required "$BOT_ENV_FILE"
bot_compose up -d bot

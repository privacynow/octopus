#!/usr/bin/env bash
# Clear persisted provider auth state from the current provider paths (best-effort).
# Use when switching accounts, troubleshooting, or changing providers.
# Providers store auth in the shared provider-auth mount under /home/bot/.provider-auth.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$REPO_DIR"
# shellcheck source=scripts/lib_env.sh
. "$REPO_DIR/scripts/lib_env.sh"

env_file="$(current_bot_env_file)"
BOT_ENV_FILE="$env_file"
export BOT_ENV_FILE
check_env_bot_required "$env_file"
provider=$(get_bot_provider "$env_file")
check_provider_image "$provider" >/dev/null

echo "Clearing provider auth state from shared provider-auth storage (no Postgres required)..."
bot_compose run --rm bot-provider sh -c '
  removed=
  for d in /home/bot/.claude /home/bot/.claude.json /home/bot/.codex; do
    if [ -d "$d" ] || [ -f "$d" ]; then
      rm -rf "$d"
      removed="$removed $d"
    fi
  done
  if [ -n "$removed" ]; then
    echo "Removed:$removed"
  else
    echo "No known provider auth paths found under /home/bot."
  fi
'

echo "Done. Run ./scripts/provider/provider_login.sh to authenticate again."

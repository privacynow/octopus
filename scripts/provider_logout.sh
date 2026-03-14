#!/usr/bin/env bash
# Clear persisted provider auth state in the bot-home volume (best-effort).
# Use when switching accounts, troubleshooting, or changing providers.
# Same image and volume as bot; does not remove the volume.
# Providers may store auth in other paths; if logout seems ineffective, re-login or check provider docs.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_DIR"
# shellcheck source=scripts/lib_env.sh
. "$(dirname "$0")/lib_env.sh"

check_env_bot_required
provider=$(get_bot_provider)
check_provider_image "$provider" >/dev/null

echo "Clearing provider auth state from bot-home volume (no Postgres required)..."
docker compose --profile bot run --rm --env-file .env.bot bot-provider sh -c '
  removed=
  for d in /home/bot/.config/Claude /home/bot/.config/claude /home/bot/.config/Codex /home/bot/.config/codex /home/bot/.config/openai /home/bot/.local/share/Claude /home/bot/.local/share/codex; do
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

echo "Done. Run ./scripts/provider_login.sh to authenticate again."

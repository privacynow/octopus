#!/usr/bin/env bash
# Clear persisted provider auth state from the current provider paths (best-effort).
# Use when switching accounts, troubleshooting, or changing providers.
# Providers store auth in the shared provider-auth mount under /home/bot/.provider-auth.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$REPO_DIR"
#
# Clear shared provider auth for one provider at a time.
# Usage: ./scripts/provider/provider_logout.sh <claude|codex>
. "$REPO_DIR/scripts/lib/bot.sh"
. "$REPO_DIR/scripts/lib/docker.sh"
. "$REPO_DIR/scripts/lib/provider.sh"

provider="${1:-${BOT_PROVIDER:-}}"
case "$provider" in
  claude|codex) ;;
  *)
    echo "Usage: ./scripts/provider/provider_logout.sh <claude|codex>" >&2
    exit 1
    ;;
esac
check_provider_image "$provider" >/dev/null
ensure_provider_auth_dir "$provider"

echo "Clearing provider auth state from shared provider-auth storage (no Postgres required)..."
provider_compose "$provider" run --rm bot-provider sh -c '
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

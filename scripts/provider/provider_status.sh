#!/usr/bin/env bash
# Report provider auth and runtime health only (not DB or Telegram).
# Uses shared per-provider auth under .deploy/provider-auth/<provider>.
# For full bot health use: ./octopus doctor [slug]
set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$REPO_DIR"
# shellcheck source=scripts/lib/bot.sh
. "$REPO_DIR/scripts/lib/bot.sh"
# shellcheck source=scripts/lib/docker.sh
. "$REPO_DIR/scripts/lib/docker.sh"
# shellcheck source=scripts/lib/provider.sh
. "$REPO_DIR/scripts/lib/provider.sh"

provider="${1:-${BOT_PROVIDER:-}}"
case "$provider" in
  claude|codex) ;;
  *)
    echo "Usage: ./scripts/provider/provider_status.sh <claude|codex>" >&2
    exit 1
    ;;
esac
check_provider_image "$provider" >/dev/null
ensure_provider_auth_dir "$provider"

echo "Provider auth and runtime only (no DB/Telegram checks)."
if ! provider_compose "$provider" run --rm bot-provider; then
  update_provider_auth_hint "$provider" "false"
  exit 1
fi
update_provider_auth_hint "$provider" "true"
echo "Success here does NOT prove a bot can start."
echo "For full bot health run: ./octopus doctor"

#!/usr/bin/env bash
# Guided provider CLI login: interactive auth, then verify with --provider-health only.
# Uses a shared per-provider auth directory under .deploy/provider-auth/<provider>.
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
else
  env_file="$(current_bot_env_file)"
  BOT_ENV_FILE="$env_file"
  export BOT_ENV_FILE
  check_env_bot_required "$env_file"
  provider=$(get_bot_provider "$env_file")
fi
check_provider_image "$provider" >/dev/null
ensure_provider_auth_dir "$provider"

echo "Provider login (BOT_PROVIDER=$provider). Uses shared provider auth under .deploy/provider-auth/$provider."
provider_compose "$provider" run --rm bot-provider sh /app/scripts/provider/container_provider_login.sh

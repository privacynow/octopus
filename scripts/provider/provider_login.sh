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

provider="${1:-${BOT_PROVIDER:-}}"
case "$provider" in
  claude|codex) ;;
  *)
    echo "Usage: ./scripts/provider/provider_login.sh <claude|codex>" >&2
    exit 1
    ;;
esac
check_provider_image "$provider" >/dev/null
ensure_provider_auth_dir "$provider"

echo "Provider login (BOT_PROVIDER=$provider). Uses shared provider auth under .deploy/provider-auth/$provider."
provider_compose "$provider" run --rm bot-provider sh /app/scripts/provider/container_provider_login.sh

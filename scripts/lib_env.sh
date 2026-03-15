# Shared env and image checks for scripts that require .env.bot.
# Source after: REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)" and cd "$REPO_DIR".
# Usage: source "$(dirname "$0")/lib_env.sh"  (from a script in scripts/).

check_env_bot_required() {
  if [ ! -f .env.bot ]; then
    echo "Create .env.bot first (TELEGRAM_BOT_TOKEN, BOT_PROVIDER, BOT_ALLOWED_USERS or BOT_ALLOW_OPEN=1)." >&2
    exit 1
  fi
}

# Echo BOT_PROVIDER from .env.bot (claude or codex), default claude. Call after check_env_bot_required.
get_bot_provider() {
  local p
  p=$(grep -E '^\s*BOT_PROVIDER=' .env.bot 2>/dev/null | sed 's/.*=\s*//' | tr -d '\r' | tr -d '"' | tr -d "'" || true)
  echo "${p:-claude}"
}

# Exit with message if image telegram-agent-bot:$1 is missing. Call with provider from get_bot_provider or arg.
check_provider_image() {
  local provider="${1:-}"
  if [ -z "$provider" ]; then
    provider=$(get_bot_provider)
  fi
  if ! docker image inspect "telegram-agent-bot:$provider" >/dev/null 2>&1; then
    echo "Image telegram-agent-bot:$provider not found." >&2
    echo "Run: ./scripts/build_bot_image.sh $provider" >&2
    exit 1
  fi
  echo "$provider"
}

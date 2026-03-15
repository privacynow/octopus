#!/usr/bin/env bash
# Run inside the bot container with bot-home volume mounted at /home/bot.
# Performs provider-specific interactive login then verifies with --provider-health only (no DB/Telegram).
set -euo pipefail

provider="${BOT_PROVIDER:-claude}"
case "$provider" in
  codex)
    echo "Starting Codex login (ChatGPT plan). Complete the sign-in in the browser."
    codex --login
    ;;
  claude)
    echo "Starting Claude. In the Claude window, run: /login"
    echo "Complete authentication in the browser, then exit Claude (e.g. /exit or Ctrl+D)."
    claude
    ;;
  *)
    echo "BOT_PROVIDER must be claude or codex, got: $provider" >&2
    exit 1
    ;;
esac

echo "Verifying provider auth (no DB or Telegram checks)..."
if ! python -m app.main --provider-health; then
  echo "Provider health check failed (see above). Re-run ./scripts/provider_login.sh or check your subscription." >&2
  exit 1
fi
echo "Provider login and health check succeeded."

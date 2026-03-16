#!/usr/bin/env bash
# Run inside the bot container with bot-home volume mounted at /home/bot.
# Performs provider-specific interactive login then verifies with --provider-health only (no DB/Telegram).
set -euo pipefail

provider="${BOT_PROVIDER:-claude}"
case "$provider" in
  codex)
    cat <<'BANNER'
╔══════════════════════════════════════════════════════════════╗
║  ACTION REQUIRED — INSIDE THE CODEX CLI                     ║
║                                                              ║
║  Complete the browser sign-in when prompted.                 ║
║  When done — press  q  or  Ctrl-C  to return to setup.       ║
║                                                              ║
║  You MUST exit the CLI to return to setup.                   ║
╚══════════════════════════════════════════════════════════════╝
BANNER
    set +e
    codex --login
    exit_code=$?
    set -e
    if [ "$exit_code" -eq 0 ]; then
      echo "✓ Codex authentication complete. Returning to setup..."
    else
      echo "✗ Authentication may have failed (exit code $exit_code). Re-run this step"
      echo "  if the provider health check fails in the next step."
    fi
    ;;
  claude)
    cat <<'BANNER'
╔══════════════════════════════════════════════════════════════╗
║  ACTION REQUIRED — INSIDE THE CLAUDE CLI                    ║
║                                                              ║
║  1. Run:  /login                                             ║
║  2. Follow the browser link to authenticate.                 ║
║  3. When done — TYPE:  /exit   (or press Ctrl-D)             ║
║                                                              ║
║  You MUST exit the CLI to return to setup.                   ║
╚══════════════════════════════════════════════════════════════╝
BANNER
    set +e
    claude
    exit_code=$?
    set -e
    if [ "$exit_code" -eq 0 ]; then
      echo "✓ Claude authentication complete. Returning to setup..."
    else
      echo "✗ Authentication may have failed (exit code $exit_code). Re-run this step"
      echo "  if the provider health check fails in the next step."
    fi
    ;;
  *)
    echo "BOT_PROVIDER must be claude or codex, got: $provider" >&2
    exit 1
    ;;
esac

echo "Verifying provider auth (no DB or Telegram checks)..."
if ! python -m app.main --provider-health; then
  echo "Provider health check failed (see above). Re-run ./scripts/provider/provider_login.sh or check your subscription." >&2
  exit 1
fi
echo "Provider login and health check succeeded."

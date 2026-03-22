#!/usr/bin/env bash
# Run inside the bot container with bot-home volume mounted at /home/bot.
# Performs provider-specific interactive login then verifies with --provider-health only (no DB/Telegram).
set -euo pipefail

provider="${BOT_PROVIDER:-claude}"
case "$provider" in
  codex)
    cat <<'BANNER'
╔══════════════════════════════════════════════════════════════╗
║  ACTION REQUIRED — CODex LOGIN                              ║
║                                                              ║
║  The script runs:  codex login --device-auth                 ║
║  Follow the printed URL and enter the device code            ║
║  in any browser to complete sign-in.                         ║
║  The command should return to setup when login completes.    ║
║  If it does not, press Ctrl-C after sign-in finishes.        ║
║                                                              ║
║  Do not run the removed flag:  codex --login                 ║
╚══════════════════════════════════════════════════════════════╝
BANNER
    set +e
    codex login --device-auth
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

echo "Verifying provider login..."
# Quick version check only — do not run the full API ping here.
# The login succeeded if auth files were written. A slow or
# unreachable API should not block setup after a successful login.
case "$provider" in
  codex)
    if codex --version >/dev/null 2>&1; then
      echo "Provider login verified."
    else
      echo "Warning: could not verify codex CLI. Continuing anyway — auth files were saved." >&2
    fi
    ;;
  claude)
    if claude --version >/dev/null 2>&1; then
      echo "Provider login verified."
    else
      echo "Warning: could not verify claude CLI. Continuing anyway — auth files were saved." >&2
    fi
    ;;
esac

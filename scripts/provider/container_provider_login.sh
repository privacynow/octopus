#!/usr/bin/env bash
# Run inside the bot container with bot-home volume mounted at /home/bot.
# Performs provider-specific interactive login then verifies the local CLI
# still works without doing a live provider runtime probe.
set -euo pipefail

provider="${BOT_PROVIDER:-claude}"

provider_has_local_auth_files() {
  local provider="$1" home_dir="${HOME:-/home/bot}"
  case "$provider" in
    claude)
      if [ -f "$home_dir/.claude.json" ] && [ -s "$home_dir/.claude.json" ]; then
        return 0
      fi
      if [ -d "$home_dir/.claude" ] && find "$home_dir/.claude" -mindepth 1 -type f -size +0c -print -quit 2>/dev/null | grep -q .; then
        return 0
      fi
      return 1
      ;;
    codex)
      local codex_home="${CODEX_HOME:-$home_dir/.codex}"
      [ -f "$codex_home/auth.json" ]
      ;;
    *)
      return 1
      ;;
  esac
}

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
    if provider_has_local_auth_files codex; then
      echo "✓ Codex authentication complete. Returning to setup..."
    else
      echo "✗ Codex authentication is still incomplete." >&2
      echo "  Complete device auth, wait for the CLI to finish, then run ./octopus again." >&2
      echo "  codex login exit code: $exit_code" >&2
      exit 1
    fi
    ;;
  claude)
    cat <<'BANNER'
╔══════════════════════════════════════════════════════════════╗
║  ACTION REQUIRED — CLAUDE CLI LOGIN                         ║
║                                                              ║
║  The CLI will prompt for authentication automatically.       ║
║  Follow the browser link to sign in.                         ║
║                                                              ║
║  If already signed in, TYPE:  /exit   (or press Ctrl-D)      ║
║  to return to setup.                                         ║
╚══════════════════════════════════════════════════════════════╝
BANNER
    # Pre-create bind-mount targets so the copy-back after login has
    # a destination even if ensure_provider_auth_dir wasn't called.
    if [ -d /home/bot/.provider-auth ]; then
      mkdir -p /home/bot/.provider-auth/.claude
    fi
    set +e
    claude
    exit_code=$?
    set -e
    # Claude CLI uses atomic writes (temp + rename) which replaces symlinks
    # with regular files in the container layer. Copy auth back to the bind
    # mount so credentials persist on the host after this container exits.
    if [ -d /home/bot/.provider-auth ]; then
      cp -a /home/bot/.claude.json /home/bot/.provider-auth/.claude.json 2>/dev/null || true
      cp -a /home/bot/.claude/* /home/bot/.provider-auth/.claude/ 2>/dev/null || true
    fi
    if provider_has_local_auth_files claude; then
      echo "✓ Claude authentication complete. Returning to setup..."
    else
      echo "✗ Claude authentication is still incomplete." >&2
      echo "  Inside Claude, run /login, complete browser auth, then /exit to return to setup." >&2
      echo "  claude exit code: $exit_code" >&2
      exit 1
    fi
    ;;
  *)
    echo "BOT_PROVIDER must be claude or codex, got: $provider" >&2
    exit 1
    ;;
esac

echo "Provider auth files saved."
echo "Octopus will run a live provider health check next."
